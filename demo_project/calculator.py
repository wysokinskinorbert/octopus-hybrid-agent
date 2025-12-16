class Calculator:
    def add(self, a, b):
        return a + b

    def subtract(self, a, b):
        return a - b

    def multiply(self, a, b):
        return a * b

    def divide(self, a, b):
        if b == 0:
            raise ZeroDivisionError('Cannot divide by zero')
        return a / b

    def power(self, base, exponent):
        if not isinstance(base, (int, float)) or not isinstance(exponent, (int, float)):
            raise TypeError('base and exponent must be numbers')
        return base ** exponent
