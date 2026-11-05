# phase2-dev-detector

```
MDB Drums, train, pipeline=detect, detector=auto (225s): onset F at 50 ms
           KD     SD     HH     TT     CY  KD/SD/HH  all 5  F@30ms track-mean
drums   0.954  0.851  0.852  0.640  0.618     0.869  0.856   0.853      0.887
mix     0.673  0.631  0.813  0.125  0.283     0.724  0.696   0.672      0.726
sep     0.880  0.709  0.853  0.593  0.485     0.811  0.792   0.777      0.804

All 5 classes: precision, recall, missed and extra strokes, mean |timing error| of the matched ones, recall in fast passages (<= 100 ms apart on one drum):
drums  P 0.826  R 0.888  missed   433 of  3850  extra   720  timing 9.1 ms  fast-passage R 0.794
mix    P 0.691  R 0.702  missed  1149 of  3850  extra  1210  timing 11.1 ms  fast-passage R 0.251
sep    P 0.854  R 0.739  missed  1006 of  3850  extra   487  timing 11.1 ms  fast-passage R 0.261

Strokes not found on their own class: what was written instead within 50 ms (rows: the recording; 'missed': nothing), and strokes written where there was none:
drums:
            KD      SD      HH      TT      CY  missed
  KD         .       5       3       .       .      25
  SD         6       .      19       .       6     135
  HH         1      11       .       .       .      76
  TT         1       6       .       .       .       .
  CY         1       5      46       .       .      87
  extra KD 19  SD 207  HH 369  TT 2  CY 13
mix:
            KD      SD      HH      TT      CY  missed
  KD         .       5      11       3       1      67
  SD        71       .      58      15      15     433
  HH        13      24       .       5      12     193
  TT         4       3       3       .       .       .
  CY        14      11      62       1       .     125
  extra KD 368  SD 198  HH 244  TT 36  CY 33
sep:
            KD      SD      HH      TT      CY  missed
  KD         .       7       9       .       .      62
  SD         8       .      73       1       9     420
  HH         2      17       .       .       6     212
  TT         1       5       1       .       .       .
  CY         1       1      46       .       .     125
  extra KD 69  SD 111  HH 105  TT 3  CY 12
```

- date: 2026-11-05 16:19
- commit: fa16547
- uncommitted_changes: False
- classifier: 4 (v2+v3)
- separation: htdemucs
- band_mix_check: HH x2 when only the separated drums hear it, KD x2 when only the separated drums hear it
- machine: Windows 11, Intel64 Family 6 Model 140 Stepping 1, GenuineIntel, Python 3.12.10
- seconds: 225
- tracks: 80sRock, BebopJazz, Britpop, CoolJazz, Disco, FunkJazz, FusionJazz, Reggae, Rock, Rockabilly, Shadows, Zeppelin
