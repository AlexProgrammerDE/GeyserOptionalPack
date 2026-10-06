#!/usr/bin/env python3
"""Original matrix reference for Bedrock 1.26.51.1 held-item research.

Python 3 standard library only. Columns are vectors; printed matrices are rows.
This models the documented ordinary-sprite and generic-block paths, not all items.
"""
import math
from functools import reduce


def identity():
    return [[float(i == j) for j in range(4)] for i in range(4)]


def multiply(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def compose(*matrices):
    return reduce(multiply, matrices, identity())


def translate(x, y, z):
    matrix = identity()
    for i, value in enumerate((x, y, z)):
        matrix[i][3] = value
    return matrix


def scale(value):
    matrix = identity()
    for i in range(3):
        matrix[i][i] = value
    return matrix


def rotate(axis, degrees):
    angle = math.radians(degrees)
    cosine, sine = math.cos(angle), math.sin(angle)
    i, j = {"x": (1, 2), "y": (2, 0), "z": (0, 1)}[axis]
    matrix = identity()
    matrix[i][i] = matrix[j][j] = cosine
    matrix[i][j], matrix[j][i] = -sine, sine
    return matrix


def inverse(matrix):
    augmented = [list(row) + unit for row, unit in zip(matrix, identity())]
    for column in range(4):
        pivot = max(range(column, 4), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("Singular transform")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(4):
            if row != column:
                coefficient = augmented[row][column]
                augmented[row] = [a - coefficient * b for a, b in zip(augmented[row], augmented[column])]
    return [row[4:] for row in augmented]
