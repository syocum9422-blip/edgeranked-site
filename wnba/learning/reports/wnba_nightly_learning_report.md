# WNBA Nightly Learning Report

Generated: 2026-07-31T04:25:07Z
Graded predictions in ledger: 2760

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
     steals           25 0.640000 0.704783    -0.093255
threes_made           16 0.625000 0.985476    -0.051613
   rebounds          252 0.618026 2.173748    -0.085827
     points          607 0.549414 5.754927    -0.177039
        pra          623 0.534091 8.125575    -0.219090

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
     ra          161 0.474026 3.619315    -0.215443
     pa          377 0.494652 6.994422    -0.231451
     pr          600 0.502530 7.469781    -0.234940
assists           98 0.505495 2.120944    -0.247738

## Biggest Misses
      date           player market  side  projection  sportsbook_line  actual_result  absolute_error
2026-05-20    Caitlin Clark    pra  over   38.941917             35.5            0.0       38.941917
2026-07-08    Caitlin Clark     pa  over   50.325903             23.5           12.0       38.325903
2026-06-25    Marina Mabrey     pr under   21.108558             25.5           59.0       37.891442
2026-06-25    Marina Mabrey    pra under   25.554953             30.5           61.0       35.445047
2026-07-08    Caitlin Clark    pra  over   51.373318             27.0           16.0       35.373318
2026-06-25    Marina Mabrey points under   18.243148             22.5           53.0       34.756852
2026-05-28  Jessica Shepard    pra under   18.114103             25.5           52.0       33.885897
2026-05-28  Jessica Shepard    pra under   18.114103             26.5           52.0       33.885897
2026-05-20    Caitlin Clark     pa  over   33.316423             30.5            0.0       33.316423
2026-07-22 Napheesa Collier     pr under    1.242045             16.5           34.0       32.757955

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
 POR          193  0.636364 6.122959
 DAL          175  0.563953 5.606513
 ATL          178  0.563218 5.475025
 LVA          225  0.557604 5.716410
 PHX          222  0.557604 6.663684
 GSV          175  0.551724 5.140257
 MIN          188  0.530055 5.973529
 NYL          261  0.529183 6.647298
 SEA          162  0.515924 6.007533
 IND          208  0.509804 6.330527
 CHI          125  0.491803 6.134583
 WAS          117  0.486957 7.960877

## Player Outliers
          player  sample_size  accuracy       mae
Napheesa Collier            5  0.600000 23.266995
    Lauren Betts           10  0.400000 11.722616
  Georgia Amoore           29  0.379310 11.167937
  Rickea Jackson            9  0.222222 11.036991
 Sabrina Ionescu           46  0.377778 10.575838
   Caitlin Clark           53  0.415094 10.523214
 Hailey Van Lith            7  0.428571  9.607210
  Brittney Sykes           36  0.400000  9.360317
   Marina Mabrey           48  0.595745  9.007011
      Awak Kuier            5  0.600000  8.677498
     Carla Leite           53  0.528302  8.655945
   Cameron Brink           20  0.333333  8.589116

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          206           0.561576                0.583448        -0.021872
           60-65%          970           0.513228                0.623853        -0.110626
           65-70%          420           0.498783                0.671349        -0.172566
             70%+         1164           0.547765                0.868791        -0.321026

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2760        6.176402        6.029090          0.301588          0.280246
 market     assists           98        2.120944        2.151619          0.322066          0.294253
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          377        6.994422        6.898161          0.317773          0.289651
 market      points          607        5.754927        5.796546          0.298628          0.279633
 market          pr          600        7.469781        7.069468          0.311649          0.289209
 market         pra          623        8.125575        7.776604          0.306852          0.281212
 market          ra          161        3.619315        3.653799          0.299196          0.289881
 market    rebounds          252        2.173748        2.212841          0.247045          0.236967
 market      steals           25        0.704783        1.592496          0.245060          0.233762
 market threes_made           16        0.985476        2.325452          0.225441          0.234656

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
