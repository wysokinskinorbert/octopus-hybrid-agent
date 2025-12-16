class Item:
    def __init__(self, name: str, price: float):
        self.name = name
        self.price = price

    def __repr__(self):
        return f"Item(name={self.name!r}, price={self.price!r})"


class Inventory:
    def __init__(self):
        self.items = []

    def add_item(self, item: Item):
        self.items.append(item)

    def total_value(self) -> float:
        return sum(item.price for item in self.items)


if __name__ == "__main__":
    inventory = Inventory()

    item1 = Item("Apple", 1.20)
    item2 = Item("Banana", 0.80)
    item3 = Item("Orange", 1.50)

    inventory.add_item(item1)
    inventory.add_item(item2)
    inventory.add_item(item3)

    total = inventory.total_value()
    print(f"Total inventory value: {total}")
