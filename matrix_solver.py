import numpy as np

# Funkcja do generowania macierzy i obliczania wyznacznika

def solve_matrix():
    # Generowanie losowej macierzy 5x5 liczb całkowitych z zakresu -10 do 10
    matrix = np.random.randint(-10, 11, size=(5, 5))
    print("Wygenerowana macierz:")
    print(matrix)

    # Obliczanie wyznacznika macierzy
    determinant = np.linalg.det(matrix)
    print(f"Wyznacznik macierzy: {determinant}")

    # Zapisywanie wyników do pliku tekstowego
    with open('matrix_output.txt', 'w') as file:
        file.write("Wygenerowana macierz:\n")
        file.write(str(matrix) + '\n\n')
        file.write(f"Wyznacznik macierzy: {determinant}\n")

# Główna funkcja uruchamiająca główny kod
if __name__ == "__main__":
    solve_matrix()
