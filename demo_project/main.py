#!/usr/bin/env python

from calculator import Calculator

def log_error(message):
    with open('output.log', 'w') as f:
        f.write(message + '\n')

def main():
    calc = Calculator()
    print("2 + 3 =", calc.add(2, 3))
    print("10 - 4 =", calc.subtract(10, 4))
    print("6 * 7 =", calc.multiply(6, 7))

    # Tests for divide
    try:
        print("8 / 2 =", calc.divide(8, 2))
    except ZeroDivisionError as e:
        log_error(f"Error: {e}")

    try:
        print("10 / 0 =", calc.divide(10, 0))
    except ZeroDivisionError as e:
        log_error(f"Error: {e}")

    # Tests for power
    print("2 ** 3 =", calc.power(2, 3))
    print("4 ** 0.5 =", calc.power(4, 0.5))
    print("3 ** -2 =", calc.power(3, -2))

if __name__ == "__main__":
    main()
