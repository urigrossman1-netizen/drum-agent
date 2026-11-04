# phase1-dev-chart

```
MDB Drums, train, pipeline=transcribe, detector=auto (148s): onset F at 50 ms
           KD     SD     HH     TT     CY  KD/SD/HH  all 5  F@30ms track-mean
drums   0.953  0.850  0.852  0.640  0.621     0.869  0.856   0.853      0.886
mix     0.676  0.631  0.813  0.125  0.283     0.724  0.696   0.672      0.726
sep     0.847  0.708  0.816  0.593  0.488     0.789  0.773   0.758      0.812

All 5 classes: precision, recall, missed and extra strokes, mean |timing error| of the matched ones, recall in fast passages (<= 100 ms apart on one drum):
drums  P 0.826  R 0.887  missed   435 of  3850  extra   717  timing 9.1 ms  fast-passage R 0.791
mix    P 0.693  R 0.700  missed  1155 of  3850  extra  1194  timing 11.1 ms  fast-passage R 0.244
sep    P 0.778  R 0.768  missed   892 of  3850  extra   846  timing 11.1 ms  fast-passage R 0.258

Strokes not found on their own class: what was written instead within 50 ms (rows: the recording; 'missed': nothing), and strokes written where there was none:
drums:
            KD      SD      HH      TT      CY  missed
  KD         .       5       3       .       .      26
  SD         6       .      19       1       6     135
  HH         1      11       .       .       .      76
  TT         1       6       .       .       .       .
  CY         1       5      46       .       .      87
  extra KD 19  SD 206  HH 369  TT 1  CY 11
mix:
            KD      SD      HH      TT      CY  missed
  KD         .       5      11       3       1      68
  SD        71       .      58      15      15     435
  HH        12      23       .       6      12     197
  TT         4       3       3       .       .       .
  CY        14      11      62       1       .     125
  extra KD 361  SD 196  HH 239  TT 35  CY 33
sep:
            KD      SD      HH      TT      CY  missed
  KD         .       7      21       .       .      45
  SD         8       .     222       1       9     272
  HH         5       8       .       .       4     109
  TT         1       5       1       .       .       .
  CY         1       1      60       .       .     112
  extra KD 124  SD 119  HH 238  TT 3  CY 8
```

- date: 2026-11-04 19:42
- commit: 9a7d6ae
- uncommitted_changes: False
- classifier: 4 (v2+v3)
- separation: htdemucs
- machine: Windows 11, Intel64 Family 6 Model 140 Stepping 1, GenuineIntel, Python 3.12.10
- seconds: 148
- tracks: 80sRock, BebopJazz, Britpop, CoolJazz, Disco, FunkJazz, FusionJazz, Reggae, Rock, Rockabilly, Shadows, Zeppelin
