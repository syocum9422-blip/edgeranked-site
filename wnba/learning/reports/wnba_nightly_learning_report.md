# WNBA Nightly Learning Report

Generated: 2026-07-18T04:25:08Z
Graded predictions in ledger: 2446

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
   rebounds          222 0.630542 2.121085    -0.079696
threes_made           16 0.625000 0.985476    -0.051613
     steals           21 0.571429 0.781642    -0.178761
     points          552 0.560886 5.699669    -0.173824
        pra          550 0.528336 8.177656    -0.238271

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
     pa          318 0.484177 7.165983    -0.257512
assists           91 0.488095 2.189458    -0.274601
     pr          539 0.496241 7.343009    -0.251432
     ra          136 0.503817 3.392629    -0.194935

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
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038

## Team Accuracy
team  sample_size  accuracy      mae
 POR          172  0.608434 6.289440
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
   Lauren Betts            8  0.375000 13.655368
 Georgia Amoore           28  0.357143 11.551602
 Rickea Jackson            9  0.222222 11.036991
Sabrina Ionescu           42  0.365854 10.794885
  Caitlin Clark           48  0.437500  9.863361
Hailey Van Lith            7  0.428571  9.607210
    Carla Leite           47  0.489362  9.509746
 Brittney Sykes           36  0.400000  9.360317
  Marina Mabrey           47  0.586957  9.089472
   Kiki Iriafen           14  0.333333  9.051917
     Awak Kuier            5  0.600000  8.677498
  Cameron Brink           20  0.333333  8.589116

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          180           0.556180                0.583167        -0.026987
           60-65%          799           0.503209                0.623520        -0.120311
           65-70%          347           0.519174                0.670971        -0.151797
             70%+         1120           0.546946                0.874600        -0.327654

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2446        6.150936        5.995968          0.306152          0.281910
 market     assists           91        2.189458        2.225736          0.329489          0.299870
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          318        7.165983        7.041098          0.327533          0.294363
 market      points          552        5.699669        5.743926          0.299318          0.277125
 market          pr          539        7.343009        6.940471          0.317486          0.292851
 market         pra          550        8.177656        7.799457          0.313973          0.284856
 market          ra          136        3.392629        3.439295          0.297270          0.287270
 market    rebounds          222        2.121085        2.154945          0.245074          0.234125
 market      steals           21        0.781642        1.858060          0.267476          0.249417
 market threes_made           16        0.985476        2.325452          0.225441          0.234656

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
