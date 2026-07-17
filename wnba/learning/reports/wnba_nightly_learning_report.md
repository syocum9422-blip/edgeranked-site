# WNBA Nightly Learning Report

Generated: 2026-07-17T04:25:09Z
Graded predictions in ledger: 2421

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
   rebounds          218 0.628141 2.117531    -0.083308
threes_made           16 0.625000 0.985476    -0.051613
     steals           21 0.571429 0.781642    -0.178761
     points          548 0.563197 5.701740    -0.172242
        pra          541 0.527881 8.198816    -0.241095

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
     pa          314 0.480769 7.201829    -0.262374
assists           90 0.481928 2.201757    -0.282534
     pr          538 0.495292 7.353612    -0.252556
     ra          134 0.496124 3.396200    -0.203759

## Biggest Misses
      date          player market  side  projection  sportsbook_line  actual_result  absolute_error
2026-05-20   Caitlin Clark    pra  over   38.941917             35.5            0.0       38.941917
2026-07-08   Caitlin Clark     pa  over   50.325903             23.5           12.0       38.325903
2026-06-25   Marina Mabrey     pr under   21.108558             25.5           59.0       37.891442
2026-06-25   Marina Mabrey    pra under   25.554953             30.5           61.0       35.445047
2026-07-08   Caitlin Clark    pra  over   51.373318             27.0           16.0       35.373318
2026-06-25   Marina Mabrey points under   18.243148             22.5           53.0       34.756852
2026-05-28 Jessica Shepard    pra under   18.114103             25.5           52.0       33.885897
2026-05-28 Jessica Shepard    pra under   18.114103             26.5           52.0       33.885897
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
 POR          161  0.612903 6.461782
 DAL          148  0.586207 5.164690
 GSV          162  0.565217 5.211409
 ATL          144  0.564286 5.252896
 LVA          211  0.563725 5.556006
 NYL          240  0.552743 6.631548
 PHX          194  0.552632 6.816062
 SEA          144  0.525180 5.728178
 MIN          156  0.523179 5.761513
 IND          188  0.518919 5.903042
 LAS          184  0.486188 5.990468
 CHI           99  0.484536 6.400723

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts            7  0.285714 15.532526
 Georgia Amoore           25  0.280000 12.512035
 Rickea Jackson            9  0.222222 11.036991
Sabrina Ionescu           42  0.365854 10.794885
  Caitlin Clark           48  0.437500  9.863361
    Carla Leite           44  0.522727  9.722699
Hailey Van Lith            7  0.428571  9.607210
   Kiki Iriafen           10  0.000000  9.506479
 Brittney Sykes           36  0.400000  9.360317
  Marina Mabrey           47  0.586957  9.089472
     Awak Kuier            5  0.600000  8.677498
  Cameron Brink           20  0.333333  8.589116

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          176           0.551724                0.583197        -0.031472
           60-65%          785           0.503268                0.623572        -0.120304
           65-70%          340           0.512048                0.670868        -0.158820
             70%+         1120           0.546946                0.874600        -0.327654

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2421        6.165088        6.001284          0.307015          0.282360
 market     assists           90        2.201757        2.235151          0.331568          0.301266
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          314        7.201829        7.049030          0.329158          0.295577
 market      points          548        5.701740        5.746122          0.298992          0.276444
 market          pr          538        7.353612        6.945759          0.317857          0.293215
 market         pra          541        8.198816        7.805762          0.315283          0.285228
 market          ra          134        3.396200        3.438085          0.299662          0.289511
 market    rebounds          218        2.117531        2.147305          0.246229          0.234939
 market      steals           21        0.781642        1.858060          0.267476          0.249417
 market threes_made           16        0.985476        2.325452          0.225441          0.234656

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
