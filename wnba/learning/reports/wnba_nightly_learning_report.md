# WNBA Nightly Learning Report

Generated: 2026-07-15T04:25:08Z
Graded predictions in ledger: 2341

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
   rebounds          206 0.640212 2.118070    -0.077199
threes_made           15 0.600000 0.966594    -0.080387
     steals           21 0.571429 0.781642    -0.178761
     points          533 0.567878 5.743585    -0.170702
        pra          520 0.529981 8.318874    -0.244768

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
assists           89 0.475610 2.212418    -0.290619
     pa          306 0.476974 7.264693    -0.269060
     ra          130 0.496000 3.440645    -0.206777
     pr          520 0.497076 7.424015    -0.255551

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
 POR          159  0.616883 6.532023
 DAL          148  0.586207 5.164690
 GSV          150  0.570470 5.401881
 ATL          144  0.564286 5.252896
 LVA          211  0.563725 5.556006
 NYL          240  0.552743 6.631548
 PHX          194  0.552632 6.816062
 MIN          153  0.527027 5.803671
 SEA          140  0.518519 5.830819
 IND          174  0.497076 6.198235
 CHI           93  0.494505 6.445044
 LAS          182  0.486034 6.014835

## Player Outliers
            player  sample_size  accuracy       mae
      Lauren Betts            7  0.285714 15.532526
    Georgia Amoore           22  0.227273 14.081145
    Rickea Jackson            9  0.222222 11.036991
   Sabrina Ionescu           42  0.365854 10.794885
     Caitlin Clark           46  0.413043 10.242299
       Carla Leite           44  0.522727  9.722699
   Hailey Van Lith            7  0.428571  9.607210
    Brittney Sykes           36  0.400000  9.360317
Michaela Onyenwere           11  0.454545  8.812463
     Natasha Cloud           17  0.529412  8.738499
     Marina Mabrey           44  0.558140  8.686572
        Awak Kuier            5  0.600000  8.677498

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          155           0.581699                0.582864        -0.001164
           60-65%          736           0.502786                0.623763        -0.120978
           65-70%          332           0.509259                0.670845        -0.161586
             70%+         1118           0.547032                0.874901        -0.327869

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2341        6.229368        6.055277          0.308392          0.282750
 market     assists           89        2.212418        2.242668          0.333729          0.302702
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          306        7.264693        7.086578          0.331921          0.297309
 market      points          533        5.743585        5.791616          0.299517          0.276210
 market          pr          520        7.424015        6.992848          0.319235          0.293523
 market         pra          520        8.318874        7.916916          0.317114          0.285799
 market          ra          130        3.440645        3.471079          0.301147          0.289867
 market    rebounds          206        2.118070        2.145344          0.244504          0.232710
 market      steals           21        0.781642        1.858060          0.267476          0.249417
 market threes_made           15        0.966594        2.280581          0.230844          0.240759

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
