from __future__ import annotations

from pydantic import BaseModel, ValidationError


class CreateERC20Args(BaseModel):
    name: str
    symbol: str
    total_supply: str
    decimals: int


def main() -> None:
    good_payload = {
        "name": "My Token",
        "symbol": "MTK",
        "total_supply": "1000000",
        "decimals": 18,
    }

    bad_payload = {
        "name": "My Token",
        "symbol": "MTK",
        "total_supply": "1000000",
        "decimals": "eighteen",
    }

    good_model = CreateERC20Args.model_validate(good_payload)
    print("validated model:")
    print(good_model)

    print("\nvalidation failure example:")
    try:
        CreateERC20Args.model_validate(bad_payload)
    except ValidationError as exc:
        for item in exc.errors():
            print(item)


if __name__ == "__main__":
    main()
