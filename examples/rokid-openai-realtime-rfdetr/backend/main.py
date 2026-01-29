from typing import Union

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class Item(BaseModel):
    name: str
    price: float
    is_offer: Union[bool, None] = None


@app.put("/example/{item_id}")
def put_example(item_id: int, item: Item):
    return {"item_name": item.name, "item_id": item_id}
