# Arnold Cat Map Mathematical Formula

## Matrix Transformation

The Arnold Cat Map uses the following linear transformation matrix:

```
A = [2 1]
    [1 1]
```

## Mathematical Formula

For a point (x, y), the transformation is:

```
[x_new]   [2 1] [x]
[y_new] = [1 1] [y] mod (width, height)
```

This expands to:
- `x_new = (2*x + y) mod width`
- `y_new = (x + y) mod height`

## Properties

1. **Determinant**: det(A) = 2×1 - 1×1 = 1
   - Area-preserving transformation
   - Invertible mapping

2. **Periodicity**: Points return to original position after finite iterations
   - Period depends on image dimensions and starting point
   - Creates chaotic but deterministic sequences

3. **Torus Topology**: Modulo operations create wrapping behavior
   - Points wrap around image boundaries
   - Maintains uniform distribution

## Implementation in Code

```python
def arnold_cat_map(self, x: int, y: int, iterations: int) -> Tuple[int, int]:
    for _ in range(iterations):
        # Arnold Cat Map matrix transformation: [2 1; 1 1]
        x_new = (2 * x + y) % self.width
        y_new = (x + y) % self.height
        x, y = x_new, y_new
    return x, y
```

## ZK-SNARK Circuit Validatio
The circuit proves knowledge of the transformation by validating:
1. Matrix multiplication follows [2 1; 1 1] form
2. Determinant equals 1 (area preservation)
3. Sequence matches expected Arnold Cat Map progression

## Example Transformation

Starting point: (25, 35) in 100×100 image

```
Step 1: [2 1] × [25] = [85] mod 100 = [85]
        [1 1]   [35]   [60]           [60]

Step 2: [2 1] × [85] = [230] mod 100 = [30]
        [1 1]   [60]   [145]           [45]

Step 3: [2 1] × [30] = [105] mod 100 = [5]
        [1 1]   [45]   [75]            [75]
```

This creates a chaotic but mathematically verifiable sequence for steganographic positioning.