# phase2b-dev-ens_4_5

```
MDB Drums, train, pipeline=detect, detector=auto (143s): onset F at 50 ms
           KD     SD     HH     TT     CY  KD/SD/HH  all 5  F@30ms track-mean
drums   0.954  0.857  0.843  0.696  0.565     0.867  0.852   0.849      0.887
mix     0.678  0.637  0.822  0.121  0.258     0.733  0.706   0.681      0.736
sep     0.846  0.710  0.816  0.609  0.458     0.789  0.773   0.758      0.825

All 5 classes: precision, recall, missed and extra strokes, mean |timing error| of the matched ones, recall in fast passages (<= 100 ms apart on one drum):
drums  P 0.819  R 0.887  missed   436 of  3850  extra   754  timing 9.1 ms  fast-passage R 0.798
mix    P 0.706  R 0.706  missed  1133 of  3850  extra  1130  timing 11.1 ms  fast-passage R 0.22
sep    P 0.771  R 0.775  missed   868 of  3850  extra   885  timing 11.1 ms  fast-passage R 0.261

Strokes not found on their own class: what was written instead within 50 ms (rows: the recording; 'missed': nothing), and strokes written where there was none:
drums:
            KD      SD      HH      TT      CY  missed
  KD         .       5       9       .       .      18
  SD         5       .      20       .       6     141
  HH         1       6       .       .       .      62
  TT         1       6       .       .       .       .
  CY         1       3      65       .       .      87
  extra KD 20  SD 187  HH 410  TT 0  CY 9
mix:
            KD      SD      HH      TT      CY  missed
  KD         .       4       9       2       1      62
  SD        72       .      69      12      11     454
  HH         7      17       .       2       8     171
  TT         5       3       2       .       .       1
  CY        14       5      64       1       .     137
  extra KD 377  SD 136  HH 256  TT 30  CY 23
sep:
            KD      SD      HH      TT      CY  missed
  KD         .       7      24       .       .      43
  SD         8       .     243       1       9     253
  HH         3       4       .       .       .      83
  TT         2       5       1       .       .       .
  CY         1       1      71       .       .     109
  extra KD 126  SD 115  HH 254  TT 0  CY 10
```

- date: 2026-11-05 22:27
- commit: 1c91256
- uncommitted_changes: False
- classifier: 4+5
- separation: htdemucs
- machine: Windows 11, Intel64 Family 6 Model 140 Stepping 1, GenuineIntel, Python 3.12.10
- seconds: 143
- tracks: 80sRock, BebopJazz, Britpop, CoolJazz, Disco, FunkJazz, FusionJazz, Reggae, Rock, Rockabilly, Shadows, Zeppelin
