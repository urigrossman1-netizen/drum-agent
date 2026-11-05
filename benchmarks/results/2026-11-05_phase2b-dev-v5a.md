# phase2b-dev-v5a

```
MDB Drums, train, pipeline=detect, detector=auto (356s): onset F at 50 ms
           KD     SD     HH     TT     CY  KD/SD/HH  all 5  F@30ms track-mean
drums   0.959  0.851  0.840  0.741  0.510     0.865  0.847   0.844      0.878
mix     0.635  0.596  0.795  0.114  0.274     0.698  0.671   0.651      0.696
sep     0.862  0.701  0.816  0.545  0.435     0.789  0.770   0.756      0.817

All 5 classes: precision, recall, missed and extra strokes, mean |timing error| of the matched ones, recall in fast passages (<= 100 ms apart on one drum):
drums  P 0.820  R 0.876  missed   477 of  3850  extra   741  timing 9.1 ms  fast-passage R 0.829
mix    P 0.668  R 0.674  missed  1257 of  3850  extra  1289  timing 11.0 ms  fast-passage R 0.171
sep    P 0.778  R 0.763  missed   914 of  3850  extra   836  timing 11.1 ms  fast-passage R 0.247

Strokes not found on their own class: what was written instead within 50 ms (rows: the recording; 'missed': nothing), and strokes written where there was none:
drums:
            KD      SD      HH      TT      CY  missed
  KD         .       5       6       .       .      18
  SD         2       .      25       1       8     142
  HH         1       9       .       .       2      84
  TT         1       4       .       .       .       .
  CY         4       5      71       .       .      89
  extra KD 17  SD 192  HH 378  TT 1  CY 9
mix:
            KD      SD      HH      TT      CY  missed
  KD         .       4      10       1       .      70
  SD       111       .      90      17      17     447
  HH        10      16       .       5      17     219
  TT         7       3       .       .       .       1
  CY        13       2      70       .       .     127
  extra KD 435  SD 137  HH 251  TT 28  CY 45
sep:
            KD      SD      HH      TT      CY  missed
  KD         .       7      16       1       1      48
  SD         8       .     215       5      10     287
  HH         6       7       .       1       3     110
  TT         2       3       1       .       .       .
  CY         .       2      82       .       .      99
  extra KD 100  SD 120  HH 223  TT 2  CY 21
```

- date: 2026-11-05 19:44
- commit: 1c91256
- uncommitted_changes: False
- classifier: 5a
- separation: htdemucs
- machine: Windows 11, Intel64 Family 6 Model 140 Stepping 1, GenuineIntel, Python 3.12.10
- seconds: 356
- tracks: 80sRock, BebopJazz, Britpop, CoolJazz, Disco, FunkJazz, FusionJazz, Reggae, Rock, Rockabilly, Shadows, Zeppelin
