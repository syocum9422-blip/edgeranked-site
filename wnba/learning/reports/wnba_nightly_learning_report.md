# WNBA Nightly Learning Report

Generated: 2026-07-05T04:25:05Z
Graded predictions in ledger: 1966

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
   rebounds          164 0.651316 2.151628    -0.086762
threes_made           13 0.615385 0.982486    -0.078350
     points          454 0.569820 5.885134    -0.186199
        pra          431 0.533800 8.329493    -0.265254
     steals           19 0.526316 0.837699    -0.234446

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
assists           81 0.472973 2.241273    -0.306458
     pa          257 0.474510 7.501043    -0.290740
     pr          441 0.502304 7.493028    -0.270446
     ra          105 0.524752 3.386510    -0.193666

## Biggest Misses
      date          player market  side  projection  sportsbook_line  actual_result  absolute_error
2026-05-20   Caitlin Clark    pra  over   38.941917             35.5            0.0       38.941917
2026-06-25   Marina Mabrey     pr under   21.108558             25.5           59.0       37.891442
2026-06-25   Marina Mabrey    pra under   25.554953             30.5           61.0       35.445047
2026-06-25   Marina Mabrey points under   18.243148             22.5           53.0       34.756852
2026-05-28 Jessica Shepard    pra under   18.114103             26.5           52.0       33.885897
2026-05-28 Jessica Shepard    pra under   18.114103             25.5           52.0       33.885897
2026-05-20   Caitlin Clark     pa  over   33.316423             30.5            0.0       33.316423
2026-06-13  Kahleah Copper    pra under   21.068592             22.5           52.0       30.931408
2026-05-20   Caitlin Clark     pr  over   30.336815             27.5            0.0       30.336815
2026-05-23  Natasha Howard    pra under   16.977403             25.5           45.0       28.022597

## Biggest Hits
      date          player   market  side  projection  sportsbook_line  actual_result  absolute_error
2026-06-25   Nyara Sabally rebounds under    4.002178              5.0            4.0        0.002178
2026-05-13 Kelsey Mitchell   steals  over    1.003325              0.5            1.0        0.003325
2026-05-09  Kahleah Copper      pra under   15.004984             23.5           15.0        0.004984
2026-06-01 Stefanie Dolson rebounds under    2.021912              4.0            2.0        0.021912
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038
2026-06-17  Kayla Thornton   points under    7.972123              9.5            8.0        0.027877
2026-05-08  Julie Allemand rebounds under    2.971458              5.0            3.0        0.028542
2026-06-24  Gabby Williams   steals under    0.968700              1.5            1.0        0.031300

## Team Accuracy
team  sample_size  accuracy      mae
 POR          144  0.611511 6.657401
 DAL          116  0.601770 5.267710
 GSV          128  0.582677 5.228105
 NYL          213  0.566667 6.464144
 ATL          119  0.560345 5.322274
 IND          139  0.547445 5.988502
 PHX          162  0.537500 7.295842
 LVA          176  0.532544 5.913517
 MIN          115  0.518182 5.455173
 SEA          123  0.516667 5.910997
 LAS          140  0.503650 6.052262
 WAS           77  0.500000 9.073645

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts            7  0.285714 15.532526
 Georgia Amoore           22  0.227273 14.081145
 Rickea Jackson            9  0.222222 11.036991
  Natasha Cloud           13  0.461538 10.696878
Sabrina Ionescu           32  0.354839 10.242522
    Carla Leite           37  0.567568 10.075768
   Kiki Iriafen            6  0.000000  9.789887
Hailey Van Lith            7  0.428571  9.607210
  Caitlin Clark           41  0.414634  9.493842
 Brittney Sykes           36  0.400000  9.360317
 Kahleah Copper           39  0.621622  9.075854
  Marina Mabrey           44  0.558140  8.686572

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          128           0.571429                0.581353        -0.009925
           60-65%          512           0.496994                0.624208        -0.127214
           65-70%          248           0.526971                0.670893        -0.143922
             70%+         1078           0.548295                0.879945        -0.331649

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         1966        6.314158        6.121493          0.315764          0.285414
 market     assists           81        2.241273        2.279686          0.338915          0.304541
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          257        7.501043        7.308174          0.340537          0.301682
 market      points          454        5.885134        5.899757          0.306771          0.278908
 market          pr          441        7.493028        7.044916          0.327580          0.296401
 market         pra          431        8.329493        7.891461          0.326838          0.289532
 market          ra          105        3.386510        3.449482          0.300865          0.287867
 market    rebounds          164        2.151628        2.190214          0.244053          0.229718
 market      steals           19        0.837699        2.000540          0.282453          0.260858
 market threes_made           13        0.982486        1.937362          0.222384          0.233427

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
