# WNBA Nightly Learning Report

Generated: 2026-07-22T04:25:08Z
Graded predictions in ledger: 2634

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
     steals           24 0.625000 0.725999    -0.111958
threes_made           16 0.625000 0.985476    -0.051613
   rebounds          244 0.622222 2.175427    -0.082623
     points          585 0.560000 5.665887    -0.169249
        pra          590 0.535959 8.002837    -0.222762

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
     ra          151 0.489655 3.597166    -0.202541
     pr          577 0.500000 7.384673    -0.241269
assists           95 0.500000 2.149676    -0.256450
     pa          351 0.502874 6.919310    -0.229001

## Biggest Misses
      date          player market  side  projection  sportsbook_line  actual_result  absolute_error
2026-05-20   Caitlin Clark    pra  over   38.941917             35.5            0.0       38.941917
2026-07-08   Caitlin Clark     pa  over   50.325903             23.5           12.0       38.325903
2026-06-25   Marina Mabrey     pr under   21.108558             25.5           59.0       37.891442
2026-06-25   Marina Mabrey    pra under   25.554953             30.5           61.0       35.445047
2026-07-08   Caitlin Clark    pra  over   51.373318             27.0           16.0       35.373318
2026-06-25   Marina Mabrey points under   18.243148             22.5           53.0       34.756852
2026-05-28 Jessica Shepard    pra under   18.114103             26.5           52.0       33.885897
2026-05-28 Jessica Shepard    pra under   18.114103             25.5           52.0       33.885897
2026-05-20   Caitlin Clark     pa  over   33.316423             30.5            0.0       33.316423
2026-06-13  Kahleah Copper    pra under   21.068592             22.5           52.0       30.931408

## Biggest Hits
      date          player   market  side  projection  sportsbook_line  actual_result  absolute_error
2026-06-25   Nyara Sabally rebounds under    4.002178              5.0            4.0        0.002178
2026-05-13 Kelsey Mitchell   steals  over    1.003325              0.5            1.0        0.003325
2026-05-09  Kahleah Copper      pra under   15.004984             23.5           15.0        0.004984
2026-07-10       Azzi Fudd       pa under   15.005129             16.5           15.0        0.005129
2026-07-07       Azzi Fudd   points under   12.008479             14.0           12.0        0.008479
2026-07-11 Breanna Stewart       ra under    9.990441             11.5           10.0        0.009559
2026-06-01 Stefanie Dolson rebounds under    2.021912              4.0            2.0        0.021912
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038

## Team Accuracy
team  sample_size  accuracy      mae
 POR          187  0.640884 6.156975
 DAL          156  0.568627 5.305960
 LVA          216  0.562500 5.492860
 PHX          210  0.560976 6.536547
 ATL          170  0.560241 5.536598
 GSV          169  0.559524 5.187949
 MIN          177  0.540698 5.500563
 NYL          253  0.538153 6.559717
 IND          200  0.517766 6.082079
 CHI          115  0.513274 5.995012
 SEA          159  0.512987 6.046195
 LAS          190  0.489247 5.861174

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts            9  0.333333 12.494574
 Georgia Amoore           29  0.379310 11.167937
 Rickea Jackson            9  0.222222 11.036991
  Caitlin Clark           51  0.431373 10.519123
Sabrina Ionescu           44  0.395349 10.399069
Hailey Van Lith            7  0.428571  9.607210
 Brittney Sykes           36  0.400000  9.360317
  Marina Mabrey           47  0.586957  9.089472
    Carla Leite           52  0.538462  8.752562
     Awak Kuier            5  0.600000  8.677498
  Cameron Brink           20  0.333333  8.589116
Chennedy Carter           18  0.277778  8.511355

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          200           0.563452                0.583317        -0.019866
           60-65%          903           0.515909                0.623637        -0.107728
           65-70%          386           0.509284                0.671043        -0.161759
             70%+         1145           0.550802                0.871364        -0.320562

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2634        6.088889        5.924070          0.301826          0.279208
 market     assists           95        2.149676        2.184588          0.324087          0.295564
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          351        6.919310        6.817221          0.318453          0.287763
 market      points          585        5.665887        5.709185          0.296922          0.276362
 market          pr          577        7.384673        6.934689          0.313405          0.290190
 market         pra          590        8.002837        7.620661          0.308743          0.281245
 market          ra          151        3.597166        3.632346          0.296005          0.286851
 market    rebounds          244        2.175427        2.212609          0.245803          0.235782
 market      steals           24        0.725999        1.657411          0.250002          0.237080
 market threes_made           16        0.985476        2.325452          0.225441          0.234656

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
