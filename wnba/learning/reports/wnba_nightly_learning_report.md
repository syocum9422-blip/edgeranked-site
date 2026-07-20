# WNBA Nightly Learning Report

Generated: 2026-07-20T04:25:08Z
Graded predictions in ledger: 2534

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
threes_made           16 0.625000 0.985476    -0.051613
   rebounds          231 0.622642 2.125784    -0.085210
     steals           23 0.608696 0.748043    -0.133347
     points          560 0.561818 5.676398    -0.171239
        pra          572 0.530756 8.131423    -0.232107

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
     pa          336 0.498498 7.007870    -0.238082
assists           93 0.500000 2.161205    -0.259643
     pr          562 0.500901 7.381744    -0.242896
     ra          140 0.503704 3.414715    -0.192956

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
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038

## Team Accuracy
team  sample_size  accuracy      mae
 POR          187  0.640884 6.156975
 DAL          148  0.586207 5.164690
 LVA          211  0.563725 5.556006
 PHX          202  0.563452 6.687099
 GSV          168  0.556886 5.199364
 NYL          245  0.553719 6.530610
 ATL          154  0.553333 5.451683
 MIN          166  0.534161 5.555588
 IND          200  0.517766 6.082079
 CHI          105  0.504854 6.149674
 SEA          150  0.503448 6.197893
 WAS          110  0.490741 8.136982

## Player Outliers
           player  sample_size  accuracy       mae
     Lauren Betts            8  0.375000 13.655368
   Georgia Amoore           29  0.379310 11.167937
   Rickea Jackson            9  0.222222 11.036991
    Caitlin Clark           51  0.431373 10.519123
  Sabrina Ionescu           44  0.395349 10.399069
  Hailey Van Lith            7  0.428571  9.607210
   Brittney Sykes           36  0.400000  9.360317
    Marina Mabrey           47  0.586957  9.089472
     Kiki Iriafen           15  0.384615  8.861857
      Carla Leite           52  0.538462  8.752562
Dominique Malonga           34  0.363636  8.685600
       Awak Kuier            5  0.600000  8.677498

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          185           0.557377                0.583305        -0.025928
           60-65%          848           0.516324                0.623603        -0.107279
           65-70%          369           0.518006                0.671063        -0.153057
             70%+         1132           0.546438                0.873161        -0.326722

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2534        6.131459        5.967214          0.303769          0.280193
 market     assists           93        2.161205        2.196827          0.325177          0.296313
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          336        7.007870        6.882964          0.320913          0.288338
 market      points          560        5.676398        5.722506          0.298213          0.276451
 market          pr          562        7.381744        6.960803          0.314905          0.291197
 market         pra          572        8.131423        7.736612          0.311434          0.283450
 market          ra          140        3.414715        3.460851          0.296313          0.286161
 market    rebounds          231        2.125784        2.163130          0.247199          0.236269
 market      steals           23        0.748043        1.726844          0.254593          0.240109
 market threes_made           16        0.985476        2.325452          0.225441          0.234656

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
