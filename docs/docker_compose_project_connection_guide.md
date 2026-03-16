# Docker、compose.yaml 与当前项目连接 PostgreSQL/Redis 的关系说明

这份文档专门解释一个很容易混淆的问题：

- 我安装了 Docker 以后，项目是怎么“连上 Docker”的？
- `compose.yaml` 是什么？
- 当前项目又是怎么连上 `PostgreSQL` 和 `Redis` 的？

一句话先说结论：

当前项目并不是“直接连接 Docker 本身”，而是“连接 Docker 里启动出来的 PostgreSQL 和 Redis 服务”。

## 1. 先分清 4 个角色

这四样东西很容易混在一起，但它们职责不同。

### 1.1 Docker Desktop / Docker daemon

它负责真正运行容器。

你安装 Docker 之后，系统里会有一个 Docker 后台服务。它能把镜像拉下来，并把容器启动起来。

### 1.2 `docker` 命令

它是你在终端里操作 Docker 的入口。

例如：

```bash
docker --version
docker ps
```

这些命令本身不保存业务配置，它们只是和 Docker 后台通信。

### 1.3 `compose.yaml`

它是“这个项目依赖哪些容器服务，以及怎么启动它们”的说明书。

当前项目的 [`compose.yaml`](/home/zhouhangmyers/python/agent-orchestrator-platform/compose.yaml) 定义了两个服务：

- `postgres`
- `redis`

也就是说，这个文件不是给 Python 代码直接读的，而是给 `docker compose` 用的。

### 1.4 Python 项目本身

当前项目的 FastAPI 应用并不会去“连接 Docker”。

它只会读取配置，然后按配置连接数据库和缓存。

## 2. `compose.yaml` 到底做了什么

当前 [`compose.yaml`](/home/zhouhangmyers/python/agent-orchestrator-platform/compose.yaml) 的核心含义可以简化成：

```yaml
services:
  postgres:
    image: postgres:16
    ports:
      - "5432:5432"

  redis:
    image: redis:7
    ports:
      - "6379:6379"
```

这表示：

- 启动一个 `PostgreSQL 16` 容器
- 启动一个 `Redis 7` 容器
- 把容器端口映射到你当前机器上的端口

其中最关键的是端口映射：

- `5432:5432`
- `6379:6379`

它的意思是：

- 你本机的 `127.0.0.1:5432` 会转发到 PostgreSQL 容器的 `5432`
- 你本机的 `127.0.0.1:6379` 会转发到 Redis 容器的 `6379`

所以虽然数据库和缓存是在 Docker 容器里跑，但从你的 Python 项目视角看，它们就像是本机上的普通服务。

## 3. 为什么安装完 Docker 后，项目不会自动连上

因为安装 Docker 只是在你机器上装好了“容器运行平台”。

但项目依赖的容器还没有启动。

只有你执行了这类命令之后：

```bash
docker compose up -d postgres redis
```

Docker 才会去读取 [`compose.yaml`](/home/zhouhangmyers/python/agent-orchestrator-platform/compose.yaml)，并真的把 `postgres` 和 `redis` 启动起来。

也就是说：

- 安装 Docker != 服务已经启动
- 有 `compose.yaml` != Docker 已经自动执行它

`compose.yaml` 只是“说明书”，不是“自动执行脚本”。

## 4. 当前项目到底是怎么连上 PostgreSQL 和 Redis 的

真正把项目连过去的是配置文件 [`.env`](/home/zhouhangmyers/python/agent-orchestrator-platform/.env)。

你现在项目里用的是这组配置：

```env
DATABASE_URL=postgresql+psycopg://agent:agent@127.0.0.1:5432/agent_platform
REDIS_URL=redis://127.0.0.1:6379/0
AUTO_CREATE_SCHEMA=false
```

这表示：

- Python 应用连接 `127.0.0.1:5432` 上的 PostgreSQL
- Python 应用连接 `127.0.0.1:6379` 上的 Redis

而这两个端口，恰好就是 Docker 通过 `compose.yaml` 暴露出来的端口。

所以真正的连接链路是：

1. Docker 启动 `postgres` 和 `redis`
2. Docker 把容器端口映射到本机 `5432` 和 `6379`
3. 项目读取 `.env`
4. 项目按 `.env` 里的地址去连

## 5. 代码里是哪几处把这些配置接起来的

### 5.1 `config.py` 负责读 `.env`

[`config.py`](/home/zhouhangmyers/python/agent-orchestrator-platform/src/agent_service/config.py) 会把 `.env` 里的环境变量读进来，构造成一个 `Settings` 对象。

这里最关键的是：

- `database_url`
- `redis_url`
- `auto_create_schema`

### 5.2 `main.py` 负责应用启动装配

[`main.py`](/home/zhouhangmyers/python/agent-orchestrator-platform/src/agent_service/main.py) 在应用启动时，会做这几件事：

1. 读取配置
2. 创建 `DatabaseManager`
3. 创建 `RuntimeService`
4. 创建 `EventCache`
5. 把这些对象挂到 `app.state`

也就是说，数据库和缓存连接是在应用启动时初始化的。

### 5.3 `session.py` 用 `DATABASE_URL` 连接数据库

[`session.py`](/home/zhouhangmyers/python/agent-orchestrator-platform/src/agent_service/db/session.py) 里的 `DatabaseManager` 会用 `database_url` 创建 SQLAlchemy engine。

当 `DATABASE_URL` 是：

```text
postgresql+psycopg://agent:agent@127.0.0.1:5432/agent_platform
```

它就会去连 Docker 里映射到本机端口的 PostgreSQL。

### 5.4 `cache_service.py` 用 `REDIS_URL` 连接 Redis

[`cache_service.py`](/home/zhouhangmyers/python/agent-orchestrator-platform/src/agent_service/services/cache_service.py) 里的 `build_event_cache(...)` 会根据 `redis_url` 来决定：

- 如果没配 `REDIS_URL`，用内存缓存
- 如果配了 `REDIS_URL`，创建 Redis 客户端

所以 Redis 这条链路也是通过 `.env` 接起来的。

## 6. Alembic 又是怎么连上 PostgreSQL 并建表的

这里是最容易误解的地方。

很多人会下意识以为：

- Docker 启动了 PostgreSQL 容器
- 所以表应该自动就有了

但实际不是。

Docker 只负责把数据库服务启动起来，不负责替你定义业务表结构。

换句话说：

- `docker compose up` 只会得到“一个能连接的 PostgreSQL 数据库”
- `alembic upgrade head` 才会把项目需要的表真正建进去

### 6.1 先记住最关键的顺序

你这个项目里，正确顺序是：

1. 启动 Docker 容器
2. 确认 `.env` 指向 PostgreSQL
3. 跑 Alembic 迁移
4. 再去看表

也就是：

```bash
docker compose up -d postgres redis
./.venv/bin/alembic upgrade head
docker exec agent-postgres psql -U agent -d agent_platform -c "\dt"
```

如果你只做了第 1 步，没有做第 2、3 步，那么你看到的通常只是“空数据库”。

### 6.2 Alembic 建表时到底依赖哪 3 样东西

Alembic 建表不是凭空发生的，它依赖三类输入。

第一类是数据库地址。

[`migrations/env.py`](/home/zhouhangmyers/python/agent-orchestrator-platform/migrations/env.py) 会读取 `DATABASE_URL`，然后连接到这个数据库。

例如你当前项目里是：

```text
postgresql+psycopg://agent:agent@127.0.0.1:5432/agent_platform
```

第二类是“目标表结构”。

[`migrations/env.py`](/home/zhouhangmyers/python/agent-orchestrator-platform/migrations/env.py) 会导入：

- [`base.py`](/home/zhouhangmyers/python/agent-orchestrator-platform/src/agent_service/db/base.py)
- [`models.py`](/home/zhouhangmyers/python/agent-orchestrator-platform/src/agent_service/db/models.py)

然后把 `Base.metadata` 交给 Alembic。

这一步的意思是：

“当前代码里，我最终想要的表结构长这样。”

第三类是 migration 脚本。

Alembic 真正执行的不是 ORM 类本身，而是 `migrations/versions/` 目录里的迁移脚本。

你当前项目已经有一个初始迁移文件：

[`20260311_0001_init_core_tables.py`](/home/zhouhangmyers/python/agent-orchestrator-platform/migrations/versions/20260311_0001_init_core_tables.py)

这个文件里写了：

- 创建 `sessions`
- 创建 `messages`
- 创建 `tool_calls`
- 创建 `workflow_runs`
- 创建 `evaluations`

### 6.3 `alembic upgrade head` 到底做了什么

这条命令的意思不是“随便建一下表”，而是：

“把当前数据库从现在的版本，升级到最新 migration 版本。”

在第一次跑的时候，数据库里通常还没有项目自己的表。

于是 Alembic 会：

1. 连接到 `agent_platform`
2. 查看数据库当前迁移版本
3. 发现还没跑过初始 migration
4. 执行 [`20260311_0001_init_core_tables.py`](/home/zhouhangmyers/python/agent-orchestrator-platform/migrations/versions/20260311_0001_init_core_tables.py) 里的 `upgrade()`
5. 在数据库里创建核心表
6. 额外创建一张 `alembic_version` 表，记录“当前数据库已经跑到哪个 migration 版本”

所以你后来看到的这张表：

- `alembic_version`

不是业务表，而是 Alembic 自己用来记迁移进度的。

### 6.4 为什么你现在必须先跑 Alembic，不能只靠应用启动

因为你当前 `.env` 已经是：

```env
AUTO_CREATE_SCHEMA=false
```

这表示应用启动时不会再调用 `create_all()` 自动建表，而是改成：

- 表结构由 Alembic 管理
- 应用只负责正常连接和读写

这么做的好处是：

- 表结构有版本记录
- 后续改表更可控
- 不会让应用启动和数据库 DDL 绑死

所以在现在这套配置下：

- 不跑 Alembic，表就不会自动出现
- 表不出现，你在 DBeaver 或 `\dt` 里就看不到业务表

### 6.5 第一次建表的完整链路

你可以把第一次建表理解成下面这条链：

```text
compose.yaml
  -> Docker 启动 PostgreSQL 容器
  -> PostgreSQL 数据库 agent_platform 可连接
  -> Alembic 读取 DATABASE_URL
  -> Alembic 导入 Base.metadata 和 models
  -> Alembic 执行 migrations/versions 里的初始脚本
  -> sessions/messages/tool_calls/workflow_runs/evaluations 被创建
  -> 你才能在数据库客户端里看到这些表
```

### 6.6 初次建表时你最常执行的命令

#### 第一步：启动依赖服务

```bash
docker compose up -d postgres redis
```

#### 第二步：确认 PostgreSQL 容器已启动

```bash
docker compose ps
```

#### 第三步：执行 Alembic

```bash
./.venv/bin/alembic upgrade head
```

#### 第四步：查看表

```bash
docker exec agent-postgres psql -U agent -d agent_platform -c "\dt"
```

或者在 `psql` 里：

```sql
\c agent_platform
\dt
```

### 6.7 如果以后 ORM 改了，Alembic 又是怎么“改表”的

这里又分成两步，不是只改 ORM 就结束。

#### 场景 A：第一次建表

如果数据库还是空的，而你已经有初始 migration，那么直接：

```bash
./.venv/bin/alembic upgrade head
```

就会把表建出来。

#### 场景 B：后续你修改了 ORM

比如你以后在 [`models.py`](/home/zhouhangmyers/python/agent-orchestrator-platform/src/agent_service/db/models.py) 的 `ToolCallRecord` 里新增一个字段：

```python
model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
```

这时正确顺序是：

1. 改 ORM 模型
2. 生成 migration 脚本
3. 检查生成结果
4. 执行 migration

命令通常是：

```bash
./.venv/bin/alembic revision --autogenerate -m "add model_name to tool_calls"
./.venv/bin/alembic upgrade head
```

第一条命令会在 `migrations/versions/` 下生成一个新的迁移文件。  
第二条命令才会真正把数据库里的表改掉。

所以最准确的理解是：

- Docker 负责把数据库服务跑起来
- Alembic 负责把数据库表结构变成项目想要的样子

### 6.8 为什么“建表后才能查看”这句话是对的

因为数据库客户端能看到的，是数据库里已经存在的对象。

如果你只是：

- 写了 ORM 类
- 写了 migration 文件

但还没执行：

```bash
./.venv/bin/alembic upgrade head
```

那这些定义还只是代码里的意图，还没有真正落到数据库里。

只有执行升级后，PostgreSQL 里真的出现表对象，你才能通过：

- `\dt`
- DBeaver
- pgAdmin

去看到它们。

## 7. 用一张图看完整关系

```text
你在 WSL 终端里执行命令
        |
        v
docker compose up -d postgres redis
        |
        v
Docker 读取 compose.yaml
        |
        v
启动两个容器：
  - postgres:16
  - redis:7
        |
        v
端口映射到本机：
  - 127.0.0.1:5432 -> postgres container:5432
  - 127.0.0.1:6379 -> redis container:6379
        |
        v
Alembic / 项目启动时读取 .env
        |
        v
config.py -> Settings
        |
        v
alembic upgrade head
        |
        +--> migrations/env.py 读取 DATABASE_URL
        |
        +--> 导入 Base.metadata 和 models
        |
        +--> 执行 migrations/versions/*.py
        |
        +--> PostgreSQL 中真正创建业务表
        |
        v
main.py 启动装配
        |
        +--> session.py 用 DATABASE_URL 连接 PostgreSQL
        |
        +--> cache_service.py 用 REDIS_URL 连接 Redis
```

## 8. 为什么在 Docker Desktop 里看不到“表”

因为 Docker Desktop 显示的主要是：

- 容器
- 镜像
- 卷
- 日志
- 文件系统

而 PostgreSQL 的“表”不是容器目录里的普通文件展示对象。

表属于数据库内部对象，要通过数据库客户端查看。

你可以用两种方式看表：

### 8.1 命令行方式

```bash
docker exec -it agent-postgres psql -U agent -d agent_platform
```

进入后执行：

```sql
\dt
```

### 8.2 图形界面方式

建议用 `DBeaver` 之类的数据库客户端连接：

- host: `127.0.0.1`
- port: `5432`
- database: `agent_platform`
- username: `agent`
- password: `agent`

## 9. 第一次接这套链路时，最容易卡住的地方

### 9.1 容器启动了，不等于表已经建好了

这是最常见误区。

`docker compose up -d postgres redis` 的结果只是：

- PostgreSQL 服务已经在线
- Redis 服务已经在线

它不等于：

- `sessions` 已经存在
- `messages` 已经存在
- `tool_calls` 已经存在

这些业务表要靠 Alembic 来建。

### 9.2 ORM 写好了，不等于数据库已经改好了

你在 [`models.py`](/home/zhouhangmyers/python/agent-orchestrator-platform/src/agent_service/db/models.py) 里改完字段后，数据库不会自动同步。

还需要：

1. 生成 migration
2. 执行 migration

### 9.3 migration 文件生成了，不等于数据库已经执行了

`alembic revision --autogenerate ...` 只是生成脚本。  
`alembic upgrade head` 才是真正执行。

### 9.4 你连错数据库时，也会误以为“没有表”

当前项目要看的库是：

```text
agent_platform
```

不是默认一定要看 `postgres` 库。

## 10. 当前项目里最容易混淆的 4 个点

### 10.1 项目不是在“连接 Docker”

项目连接的是：

- PostgreSQL 服务
- Redis 服务

只是这两个服务恰好运行在 Docker 容器里。

### 10.2 `compose.yaml` 不会自动执行

你必须手动运行：

```bash
docker compose up -d postgres redis
```

Docker 才会按它的说明去启动服务。

### 10.3 `.env` 和 `compose.yaml` 分工不同

- `compose.yaml`：定义容器怎么启动
- `.env`：告诉 Python 代码去连哪里

### 10.4 Alembic 也不关心 Docker

Alembic 只关心数据库连接串。

只要 `DATABASE_URL` 指向 Docker 暴露出来的 PostgreSQL 端口，它就能工作。

## 11. 当前项目最实用的排查命令

### 看容器有没有起来

```bash
docker compose ps
```

### 看 PostgreSQL 是否能列出表

```bash
docker exec agent-postgres psql -U agent -d agent_platform -c "\dt"
```

### 看当前数据库迁移版本

```bash
docker exec agent-postgres psql -U agent -d agent_platform -c "select * from alembic_version;"
```

### 重新执行到最新迁移版本

```bash
./.venv/bin/alembic upgrade head
```

### 看 Redis 是否正常响应

```bash
docker exec agent-redis redis-cli ping
```

正常情况下你会看到：

```text
PONG
```

## 12. 如果以后应用自己也放进 Docker，会有什么变化

当前项目是“应用跑在本机/WSL，依赖服务跑在 Docker 里”。

所以配置里用的是：

```text
127.0.0.1:5432
127.0.0.1:6379
```

如果以后你把 FastAPI 应用本身也放进 Docker Compose，那么容器之间通常就不再用 `127.0.0.1` 通信，而会直接用服务名：

```text
postgresql+psycopg://agent:agent@postgres:5432/agent_platform
redis://redis:6379/0
```

因为那时应用和数据库都在同一个 Docker 网络里。

## 13. 一句话总结

你当前项目的真实关系不是：

```text
项目 -> Docker
```

而是：

```text
项目 -> .env 里的连接串 -> localhost 端口 -> Docker 容器里的 PostgreSQL / Redis
```

`compose.yaml` 的作用，是帮你把这些依赖服务启动起来；`.env` 的作用，是告诉项目去哪里连接这些服务。
