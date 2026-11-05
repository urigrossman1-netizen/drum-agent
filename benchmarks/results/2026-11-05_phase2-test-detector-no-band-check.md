# phase2-test-detector-no-band-check

```
MDB Drums, test, pipeline=detect, detector=auto (246s): onset F at 50 ms
           KD     SD     HH     TT     CY  KD/SD/HH  all 5  F@30ms track-mean
drums   0.963  0.866  0.723  0.495  0.270     0.837  0.772   0.766      0.830
mix     0.706  0.688  0.611  0.307  0.094     0.664  0.591   0.579      0.654
sep     0.945  0.823  0.700  0.415  0.141     0.807  0.732   0.723      0.823

All 5 classes: precision, recall, missed and extra strokes, mean |timing error| of the matched ones, recall in fast passages (<= 100 ms apart on one drum):
drums  P 0.779  R 0.764  missed   961 of  4074  extra   882  timing 8.6 ms  fast-passage R 0.678
mix    P 0.624  R 0.562  missed  1786 of  4074  extra  1376  timing 9.2 ms  fast-passage R 0.428
sep    P 0.762  R 0.703  missed  1208 of  4074  extra   893  timing 9.6 ms  fast-passage R 0.551

Strokes not found on their own class: what was written instead within 50 ms (rows: the recording; 'missed': nothing), and strokes written where there was none:
drums:
            KD      SD      HH      TT      CY  missed
  KD         .       7      11       .       .      25
  SD         3       .      14       .       1     148
  HH         .       7       .       .       6      71
  TT         1      20       7       .       1      21
  CY         1      21     342       .       .     254
  extra KD 16  SD 144  HH 271  TT 1  CY 8
mix:
            KD      SD      HH      TT      CY  missed
  KD         .      21      56       4       1     150
  SD        28       .      42      30       4     436
  HH        12      22       .       3      24     216
  TT         4       5       1       .       1      31
  CY        64      18     316      13       .     284
  extra KD 199  SD 128  HH 276  TT 57  CY 47
sep:
            KD      SD      HH      TT      CY  missed
  KD         .       7      13       .       .      44
  SD         4       .      33       .       4     251
  HH         .       7       .       .      12     103
  TT         2      14       4       .       2      31
  CY         8      25     376       1       .     267
  extra KD 16  SD 111  HH 237  TT 8  CY 9
```

- date: 2026-11-05 16:44
- commit: fa16547
- uncommitted_changes: False
- classifier: 4 (v2+v3)
- separation: htdemucs
- band_mix_check: off
- machine: Windows 11, Intel64 Family 6 Model 140 Stepping 1, GenuineIntel, Python 3.12.10
- seconds: 246
- tracks: Beatles, Country1, FreeJazz, Gospel, Grunge, Hendrix, LatinJazz, ModalJazz, Punk, SpeedMetal, SwingJazz
