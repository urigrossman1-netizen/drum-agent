# phase2-dev-oaf-evidence

```
MDB Drums, train: our classifier with oaf as evidence {"agree": {"KD": 0.5, "TT": 0.75}, "alone": {"KD": 1.5}, "source": "oaf"}: onset F at 50 ms
           KD     SD     HH     TT     CY  KD/SD/HH  all 5  F@30ms track-mean
drums   0.960  0.851  0.852  0.667  0.618     0.870  0.857   0.854      0.887
sep     0.879  0.709  0.815  0.600  0.486     0.794  0.777   0.763      0.813

All 5 classes: precision, recall, missed and extra strokes, mean |timing error| of the matched ones, recall in fast passages (<= 100 ms apart on one drum):
drums  P 0.827  R 0.889  missed   427 of  3850  extra   718  timing 9.1 ms  fast-passage R 0.794
sep    P 0.788  R 0.767  missed   898 of  3850  extra   792  timing 11.1 ms  fast-passage R 0.265

Strokes not found on their own class: what was written instead within 50 ms (rows: the recording; 'missed': nothing), and strokes written where there was none:
drums:
            KD      SD      HH      TT      CY  missed
  KD         .       4       5       .       .      19
  SD         6       .      18       .       6     136
  HH         1      11       .       .       .      76
  TT         1       5       .       .       .       .
  CY         1       5      46       .       .      87
  extra KD 16  SD 209  HH 368  TT 3  CY 13
sep:
            KD      SD      HH      TT      CY  missed
  KD         .       6      25       .       .      51
  SD         8       .     222       1       9     271
  HH         2       8       .       .       4     111
  TT         1       4       1       .       .       .
  CY         1       1      59       .       .     113
  extra KD 65  SD 122  HH 238  TT 5  CY 10
```

- date: 2026-11-05 16:59
- commit: 7bbb6d0
- uncommitted_changes: False
- classifier: 4 (v2+v3)
- separation: htdemucs
- machine: Windows 11, Intel64 Family 6 Model 140 Stepping 1, GenuineIntel, Python 3.12.10
- seconds: 82
- model: oaf
- model_revision: 771fd5529062b9f6f0b58f01cc4b9819db046f4a
- evidence: {"agree": {"KD": 0.5, "TT": 0.75}, "alone": {"KD": 1.5}}
- tracks: 80sRock, BebopJazz, Britpop, CoolJazz, Disco, FunkJazz, FusionJazz, Reggae, Rock, Rockabilly, Shadows, Zeppelin
