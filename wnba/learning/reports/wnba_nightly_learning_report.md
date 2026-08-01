# WNBA Nightly Learning Report

Generated: 2026-08-01T04:25:07Z
Graded predictions in ledger: 2806

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
     steals           25 0.640000 0.704783    -0.093255
threes_made           16 0.625000 0.985476    -0.051613
   rebounds          254 0.617021 2.174958    -0.086074
     points          613 0.548922 5.770305    -0.176454
        pra          634 0.526316 8.162772    -0.225323

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
     ra          165 0.474684 3.618060    -0.212865
     pa          387 0.496084 6.909612    -0.227202
     pr          613 0.500000 7.502739    -0.236021
assists           98 0.505495 2.120944    -0.247738

## Biggest Misses
      date           player market  side  projection  sportsbook_line  actual_result  absolute_error
2026-05-20    Caitlin Clark    pra  over   38.941917             35.5            0.0       38.941917
2026-07-08    Caitlin Clark     pa  over   50.325903             23.5           12.0       38.325903
2026-06-25    Marina Mabrey     pr under   21.108558             25.5           59.0       37.891442
2026-06-25    Marina Mabrey    pra under   25.554953             30.5           61.0       35.445047
2026-07-08    Caitlin Clark    pra  over   51.373318             27.0           16.0       35.373318
2026-06-25    Marina Mabrey points under   18.243148             22.5           53.0       34.756852
2026-05-28  Jessica Shepard    pra under   18.114103             26.5           52.0       33.885897
2026-05-28  Jessica Shepard    pra under   18.114103             25.5           52.0       33.885897
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
 PHX          222  0.557604 6.663684
 LVA          230  0.554054 5.810173
 GSV          175  0.551724 5.140257
 MIN          194  0.534392 5.907144
 NYL          267  0.524715 6.632729
 SEA          162  0.515924 6.007533
 IND          208  0.509804 6.330527
 CHI          136  0.500000 5.979297
 WAS          117  0.486957 7.960877

## Player Outliers
          player  sample_size  accuracy       mae
Napheesa Collier            8  0.750000 15.936543
    Lauren Betts           10  0.400000 11.722616
  Georgia Amoore           29  0.379310 11.167937
  Rickea Jackson            9  0.222222 11.036991
   Caitlin Clark           53  0.415094 10.523214
 Sabrina Ionescu           47  0.391304 10.374528
 Hailey Van Lith            7  0.428571  9.607210
  Brittney Sykes           36  0.400000  9.360317
   Marina Mabrey           48  0.595745  9.007011
      Awak Kuier            5  0.600000  8.677498
     Carla Leite           53  0.528302  8.655945
   Cameron Brink           20  0.333333  8.589116

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          212           0.562500                0.583423        -0.020923
           60-65%          998           0.508736                0.623876        -0.115140
           65-70%          429           0.490476                0.671452        -0.180976
             70%+         1167           0.548951                0.868665        -0.319714

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2806        6.192854        6.039939          0.301564          0.280852
 market     assists           98        2.120944        2.151619          0.322066          0.294253
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          387        6.909612        6.811329          0.315920          0.288661
 market      points          613        5.770305        5.812697          0.298555          0.279772
 market          pr          613        7.502739        7.080250          0.311180          0.289406
 market         pra          634        8.162772        7.811751          0.308244          0.283740
 market          ra          165        3.618060        3.666505          0.298439          0.290130
 market    rebounds          254        2.174958        2.213823          0.247139          0.237198
 market      steals           25        0.704783        1.592496          0.245060          0.233762
 market threes_made           16        0.985476        2.325452          0.225441          0.234656

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
