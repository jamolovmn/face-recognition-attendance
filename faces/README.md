# faces/

One folder per person, 5-10 photos each (front, slight left/right, with/without glasses, different light):

```
faces/
  Ali Valiyev/
    1.jpg
    2.jpg
  Dilnoza Karimova/
    1.jpg
```

The folder name is the name that appears in Nextcloud. Then run `python -m attendance.enroll`.
Photos here are biometric data: they are git-ignored on purpose, never commit them.
