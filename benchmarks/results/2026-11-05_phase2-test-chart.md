# phase2-test-chart

```
MDB Drums, test, pipeline=transcribe, detector=auto (411s): onset F at 50 ms
           KD     SD     HH     TT     CY  KD/SD/HH  all 5  F@30ms track-mean
drums   0.963  0.865  0.724  0.495  0.270     0.837  0.771   0.766      0.830
mix     0.708  0.687  0.612  0.292  0.094     0.665  0.592   0.579      0.655
sep     0.932  0.822  0.676  0.415  0.145     0.800  0.722   0.716      0.799

All 5 classes: precision, recall, missed and extra strokes, mean |timing error| of the matched ones, recall in fast passages (<= 100 ms apart on one drum):
drums  P 0.780  R 0.763  missed   964 of  4074  extra   879  timing 8.5 ms  fast-passage R 0.671
mix    P 0.626  R 0.561  missed  1790 of  4074  extra  1362  timing 9.2 ms  fast-passage R 0.414
sep    P 0.798  R 0.660  missed  1387 of  4074  extra   680  timing 9.4 ms  fast-passage R 0.545

Strokes not found on their own class: what was written instead within 50 ms (rows: the recording; 'missed': nothing), and strokes written where there was none:
drums:
            KD      SD      HH      TT      CY  missed
  KD         .       7      11       .       .      25
  SD         3       .      14       .       1     151
  HH         .       7       .       .       6      71
  TT         1      20       7       .       1      21
  CY         1      21     342       .       .     254
  extra KD 16  SD 144  HH 268  TT 1  CY 8
mix:
            KD      SD      HH      TT      CY  missed
  KD         .      20      56       4       1     151
  SD        28       .      42      31       4     437
  HH        11      22       .       3      24     217
  TT         4       5       1       .       1      33
  CY        63      19     317      13       .     283
  extra KD 196  SD 127  HH 270  TT 55  CY 45
sep:
            KD      SD      HH      TT      CY  missed
  KD         .       8      13       .       .      67
  SD         5       .      11       .       4     273
  HH         .      17       .       .      12     249
  TT         3      14       .       .       3      33
  CY         7      29     289       1       .     349
  extra KD 13  SD 96  HH 136  TT 8  CY 11
```

- date: 2026-11-05 16:51
- commit: fa16547
- uncommitted_changes: False
- classifier: 4 (v2+v3)
- separation: htdemucs
- band_mix_check: HH x2 when only the separated drums hear it, KD x2 when only the separated drums hear it
- machine: Windows 11, Intel64 Family 6 Model 140 Stepping 1, GenuineIntel, Python 3.12.10
- seconds: 411
- tracks: Beatles, Country1, FreeJazz, Gospel, Grunge, Hendrix, LatinJazz, ModalJazz, Punk, SpeedMetal, SwingJazz
