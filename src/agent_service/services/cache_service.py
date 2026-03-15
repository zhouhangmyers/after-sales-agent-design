from __future__ import annotations

import json
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Protocol, cast


class EventCache(Protocol):
    # EventCache 定义了“事件缓存”最小需要提供的能力。
    # 上层代码只依赖这个协议，不关心底层到底是内存实现还是 Redis 实现。
    def set_json(self, key: str, payload: dict[str, Any]) -> None:
        # 按 key 存一份 JSON 对象。
        ...

    def get_json(self, key: str) -> dict[str, Any] | None:
        # 按 key 读取一份 JSON 对象；如果不存在就返回 None。
        ...

# dataclass 会自动生成 __init__ 等样板代码，适合这种主要承载状态的小型类。
# slots=True 表示实例只允许拥有已声明的属性，能减少一点内存占用，也避免误写新属性。
# 这里大致可以理解成手写了下面这样的代码：
# class InMemoryEventCache:
#     __slots__ = ("_store", "_lock") 只允许实例有这两个变量，后续不能加
#
#     def __init__(
#         self,
#         _store: dict[str, str] | None = None,
#         _lock: Lock | None = None,
#     ) -> None:
#         self._store = {} if _store is None else _store
#         self._lock = Lock() if _lock is None else _lock
@dataclass(slots=True)
class InMemoryEventCache:
    # _store 是进程内缓存本体。
    # 这里统一把 payload 编码成 JSON 字符串保存，
    # 这样和 Redis 版的行为保持一致，而不是直接暴露原始 dict 引用。
    _store: dict[str, str] = field(default_factory=dict)
    # 多线程场景下，读写共享字典时需要加锁，避免状态竞争。
    _lock: Lock = field(default_factory=Lock)

    def set_json(self, key: str, payload: dict[str, Any]) -> None:
        # 先把字典编码成 JSON 字符串。
        # ensure_ascii=False 可以保留中文等非 ASCII 字符，避免变成 \uXXXX。
        encoded = json.dumps(payload, ensure_ascii=False)
        # 只在真正写共享存储时持有锁，尽量缩短临界区。
        with self._lock:
            self._store[key] = encoded

    def get_json(self, key: str) -> dict[str, Any] | None:
        # 先在锁内读取字符串值，保证读操作线程安全。
        with self._lock:
            encoded = self._store.get(key)
        if encoded is None:
            return None
        # 读到后再反序列化回 Python 字典。
        return json.loads(encoded)


class RedisEventCache:
    def __init__(self, redis_url: str) -> None:
        # 延迟导入 redis，避免在不使用 Redis 的场景下也强依赖这个包。
        from redis import Redis

        # 根据 redis_url 创建客户端。
        # decode_responses=True 表示尽量直接返回 str，而不是 bytes。
        self._client = Redis.from_url(redis_url, decode_responses=True)

    def set_json(self, key: str, payload: dict[str, Any]) -> None:
        # Redis 里同样存 JSON 字符串，保持和内存版一致的接口语义。
        self._client.set(key, json.dumps(payload, ensure_ascii=False))

    def get_json(self, key: str) -> dict[str, Any] | None:
        # 从 Redis 读取指定 key 对应的值。
        encoded = self._client.get(key)
        if encoded is None:
            return None
        # 理论上 decode_responses=True 后通常拿到的是 str，
        # 这里仍然兼容 bytes，避免客户端配置差异导致的问题。
        if isinstance(encoded, bytes):
            encoded = encoded.decode()
        # 如果最终不是字符串，说明数据形态不符合当前缓存协议，直接返回 None。
        if not isinstance(encoded, str):
            return None
        # json.loads 返回值在类型系统里比较宽泛；
        # 这里通过 cast 告诉类型检查器：当前协议约定它应该是 dict[str, Any]。
        return cast(dict[str, Any], json.loads(encoded))


def build_event_cache(redis_url: str | None) -> EventCache:
    # 没有配置 Redis 时，默认退回到最简单的内存缓存，方便本地开发和演示。
    if not redis_url:
        return InMemoryEventCache()
    try:
        # 配了 redis_url 就优先使用 Redis，实现跨进程/跨实例共享缓存。
        return RedisEventCache(redis_url)
    except Exception:
        # 如果 Redis 初始化失败，继续回退到内存缓存，保证服务还能启动。
        # 这种设计更偏向可用性优先，但也意味着错误会被静默吞掉。
        return InMemoryEventCache()
