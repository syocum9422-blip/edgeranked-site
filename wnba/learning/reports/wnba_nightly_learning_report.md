# WNBA Nightly Learning Report

Generated: 2026-07-19T04:25:09Z
Graded predictions in ledger: 2488

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
threes_made           16 0.625000 0.985476    -0.051613
   rebounds          226 0.623188 2.125395    -0.086623
     steals           22 0.590909 0.779331    -0.156681
     points          555 0.563303 5.690335    -0.170913
        pra          560 0.526032 8.209647    -0.239344

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
     pa          327 0.490741 7.093859    -0.249054
     pr          550 0.493554 7.452829    -0.252232
assists           92 0.494118 2.180264    -0.267194
     ra          139 0.507463 3.406692    -0.189965

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
 LVA          211  0.563725 5.556006
 PHX          202  0.563452 6.687099
 ATL          154  0.553333 5.451683
 NYL          240  0.552743 6.631548
 MIN          156  0.523179 5.761513
 IND          192  0.518519 6.141397
 CHI          105  0.504854 6.149674
 SEA          150  0.503448 6.197893
 LAS          187  0.483696 5.927445

## Player Outliers
           player  sample_size  accuracy       mae
     Lauren Betts            8  0.375000 13.655368
   Georgia Amoore           28  0.357143 11.551602
   Rickea Jackson            9  0.222222 11.036991
  Sabrina Ionescu           42  0.365854 10.794885
    Caitlin Clark           50  0.420000 10.685953
  Hailey Van Lith            7  0.428571  9.607210
      Carla Leite           47  0.489362  9.509746
   Brittney Sykes           36  0.400000  9.360317
    Marina Mabrey           47  0.586957  9.089472
     Kiki Iriafen           14  0.333333  9.051917
Dominique Malonga           34  0.363636  8.685600
       Awak Kuier            5  0.600000  8.677498

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          180           0.556180                0.583167        -0.026987
           60-65%          818           0.506901                0.623658        -0.116758
           65-70%          359           0.512821                0.670922        -0.158101
             70%+         1131           0.546931                0.873291        -0.326360

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2488        6.174658        6.017995          0.305491          0.281661
 market     assists           92        2.180264        2.213096          0.327178          0.297955
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          327        7.093859        6.976452          0.324260          0.291489
 market      points          555        5.690335        5.736393          0.298370          0.276258
 market          pr          550        7.452829        7.045665          0.317682          0.293718
 market         pra          560        8.209647        7.826646          0.313664          0.285392
 market          ra          139        3.406692        3.454408          0.295927          0.285882
 market    rebounds          226        2.125395        2.160412          0.247573          0.236349
 market      steals           22        0.779331        1.800639          0.259602          0.243589
 market threes_made           16        0.985476        2.325452          0.225441          0.234656

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
