# phase2-dev-adt-str-evidence

```
MDB Drums, train: our classifier with adt_str as evidence {"agree": {"CY": 0.5, "TT": 0.5}, "alone": {"HH": 1.25, "KD": 2.0}, "source": "adt_str"}: onset F at 50 ms
           KD     SD     HH     TT     CY  KD/SD/HH  all 5  F@30ms track-mean
drums   0.956  0.851  0.863  0.786  0.729     0.875  0.866   0.863      0.885
sep     0.906  0.709  0.817  0.667  0.515     0.799  0.782   0.767      0.807

All 5 classes: precision, recall, missed and extra strokes, mean |timing error| of the matched ones, recall in fast passages (<= 100 ms apart on one drum):
drums  P 0.848  R 0.883  missed   449 of  3850  extra   608  timing 9.1 ms  fast-passage R 0.794
sep    P 0.811  R 0.755  missed   942 of  3850  extra   676  timing 11.1 ms  fast-passage R 0.265

Strokes not found on their own class: what was written instead within 50 ms (rows: the recording; 'missed': nothing), and strokes written where there was none:
drums:
            KD      SD      HH      TT      CY  missed
  KD         .       5       .       .       .      30
  SD         2       .       8       .       9     147
  HH         2      24       .       .      11     119
  TT         1       3       .       .       .       .
  CY         1       3      15       .       .      69
  extra KD 16  SD 199  HH 282  TT 2  CY 25
sep:
            KD      SD      HH      TT      CY  missed
  KD         .       8      15       .       .      58
  SD         8       .     198       1       9     295
  HH         4      12       .       1       7     160
  TT         1       4       .       .       .       .
  CY         1       .      53       .       .     107
  extra KD 25  SD 117  HH 186  TT 3  CY 23
```

- date: 2026-11-05 17:01
- commit: 7bbb6d0
- uncommitted_changes: False
- classifier: 4 (v2+v3)
- separation: htdemucs
- machine: Windows 11, Intel64 Family 6 Model 140 Stepping 1, GenuineIntel, Python 3.12.10
- seconds: 66
- model: adt_str
- model_revision: a33c5c6b191a4ca1e0f6dc22140947485eb36ce8
- evidence: {"agree": {"CY": 0.5, "TT": 0.5}, "alone": {"HH": 1.25, "KD": 2.0}}
- tracks: 80sRock, BebopJazz, Britpop, CoolJazz, Disco, FunkJazz, FusionJazz, Reggae, Rock, Rockabilly, Shadows, Zeppelin
