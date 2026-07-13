# WNBA Nightly Learning Report

Generated: 2026-07-13T04:25:07Z
Graded predictions in ledger: 2263

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
   rebounds          199 0.648352 2.135387    -0.071849
threes_made           15 0.600000 0.966594    -0.080387
     points          517 0.562130 5.778495    -0.179428
     steals           20 0.550000 0.797309    -0.202699
        pra          503 0.532000 8.293050    -0.246590

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
assists           88 0.469136 2.228890    -0.298755
     pa          300 0.476510 7.309789    -0.271449
     pr          499 0.502033 7.366116    -0.254789
     ra          121 0.504274 3.461114    -0.204062

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
 POR          159  0.616883 6.532023
 DAL          139  0.602941 5.072881
 GSV          150  0.570470 5.401881
 LVA          204  0.568528 5.539082
 PHX          186  0.565934 6.932548
 NYL          232  0.563319 6.469550
 ATL          134  0.534351 5.367371
 MIN          143  0.514493 5.949557
 IND          166  0.509202 6.112506
 SEA          137  0.507576 5.745506
 WAS           79  0.493506 9.045986
 CHI           88  0.488372 6.430968

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts            7  0.285714 15.532526
 Georgia Amoore           22  0.227273 14.081145
 Rickea Jackson            9  0.222222 11.036991
  Caitlin Clark           43  0.395349 10.766204
Sabrina Ionescu           38  0.405405  9.953735
    Carla Leite           44  0.522727  9.722699
Hailey Van Lith            7  0.428571  9.607210
 Brittney Sykes           36  0.400000  9.360317
  Natasha Cloud           16  0.500000  9.146459
  Marina Mabrey           44  0.558140  8.686572
   Kiki Iriafen            7  0.000000  8.657472
  Cameron Brink           20  0.333333  8.589116

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          153           0.582781                0.582704         0.000077
           60-65%          686           0.504491                0.623785        -0.119294
           65-70%          316           0.508091                0.670890        -0.162799
             70%+         1108           0.546544                0.876044        -0.329500

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2263        6.230108        6.069342          0.309938          0.283254
 market     assists           88        2.228890        2.255785          0.336067          0.304364
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          300        7.309789        7.143286          0.333340          0.297594
 market      points          517        5.778495        5.831254          0.302774          0.279004
 market          pr          499        7.366116        6.984110          0.320092          0.292991
 market         pra          503        8.293050        7.881846          0.318237          0.285494
 market          ra          121        3.461114        3.513399          0.301912          0.289391
 market    rebounds          199        2.135387        2.162899          0.243192          0.231437
 market      steals           20        0.797309        1.919237          0.276350          0.256212
 market threes_made           15        0.966594        2.280581          0.230844          0.240759

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
