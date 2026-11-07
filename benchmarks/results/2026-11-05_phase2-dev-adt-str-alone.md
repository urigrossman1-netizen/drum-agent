# phase2-dev-adt-str-alone

```
MDB Drums, train: adt_str alone: onset F at 50 ms
           KD     SD     HH     TT     CY  KD/SD/HH  all 5  F@30ms track-mean
drums   0.887  0.737  0.720  0.788  0.553     0.761  0.745   0.735      0.735
sep     0.893  0.671  0.758  0.629  0.352     0.757  0.731   0.712      0.745

All 5 classes: precision, recall, missed and extra strokes, mean |timing error| of the matched ones, recall in fast passages (<= 100 ms apart on one drum):
drums  P 0.826  R 0.679  missed  1236 of  3850  extra   551  timing 10.7 ms  fast-passage R 0.397
sep    P 0.846  R 0.644  missed  1372 of  3850  extra   451  timing 12.5 ms  fast-passage R 0.181

Strokes not found on their own class: what was written instead within 50 ms (rows: the recording; 'missed': nothing), and strokes written where there was none:
drums:
            KD      SD      HH      TT      CY  missed
  KD         .       5       1       1       .      60
  SD        13       .      16       1       5     398
  HH        12      95       .       .      62     444
  TT         1       1       .       .       .       .
  CY         3       2       5       .       .     111
  extra KD 56  SD 85  HH 136  TT 3  CY 48
sep:
            KD      SD      HH      TT      CY  missed
  KD         .       3       1       .       .      78
  SD        11       .      69       1       1     520
  HH         8      23       .       .      35     425
  TT         1       3       .       .       .       .
  CY         2       .      30       .       .     161
  extra KD 35  SD 58  HH 118  TT 8  CY 44
```

- date: 2026-11-05 16:58
- commit: 7bbb6d0
- uncommitted_changes: False
- classifier: 4 (v2+v3)
- separation: htdemucs
- machine: Windows 11, Intel64 Family 6 Model 140 Stepping 1, GenuineIntel, Python 3.12.10
- seconds: 1
- model: adt_str
- model_revision: a33c5c6b191a4ca1e0f6dc22140947485eb36ce8
- evidence: None
- tracks: 80sRock, BebopJazz, Britpop, CoolJazz, Disco, FunkJazz, FusionJazz, Reggae, Rock, Rockabilly, Shadows, Zeppelin
