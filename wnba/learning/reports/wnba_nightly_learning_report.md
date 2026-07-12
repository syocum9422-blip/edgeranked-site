# WNBA Nightly Learning Report

Generated: 2026-07-12T04:25:07Z
Graded predictions in ledger: 2223

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
   rebounds          191 0.637931 2.154150    -0.086405
threes_made           15 0.600000 0.966594    -0.080387
     points          510 0.560000 5.804358    -0.183185
        pra          493 0.532653 8.280131    -0.249042
     steals           19 0.526316 0.837699    -0.234446

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
assists           87 0.462500 2.247106    -0.307091
     pa          298 0.476351 7.288379    -0.272245
     ra          117 0.495575 3.484947    -0.216187
     pr          492 0.501031 7.377112    -0.257721

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
2026-06-01 Stefanie Dolson rebounds under    2.021912              4.0            2.0        0.021912
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038
2026-06-17  Kayla Thornton   points under    7.972123              9.5            8.0        0.027877

## Team Accuracy
team  sample_size  accuracy      mae
 DAL          139  0.602941 5.072881
 POR          151  0.595890 6.636877
 GSV          150  0.570470 5.401881
 NYL          227  0.566964 6.449234
 LVA          195  0.558511 5.685505
 PHX          178  0.557471 6.948850
 ATL          127  0.556452 5.255667
 IND          166  0.509202 6.112506
 SEA          137  0.507576 5.745506
 MIN          140  0.503704 6.006031
 WAS           79  0.493506 9.045986
 CHI           88  0.488372 6.430968

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts            7  0.285714 15.532526
 Georgia Amoore           22  0.227273 14.081145
 Rickea Jackson            9  0.222222 11.036991
  Caitlin Clark           43  0.395349 10.766204
    Carla Leite           42  0.500000  9.900387
Hailey Van Lith            7  0.428571  9.607210
Sabrina Ionescu           36  0.428571  9.573670
 Brittney Sykes           36  0.400000  9.360317
  Natasha Cloud           16  0.500000  9.146459
  Marina Mabrey           44  0.558140  8.686572
   Kiki Iriafen            7  0.000000  8.657472
  Cameron Brink           20  0.333333  8.589116

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          147           0.572414                0.582316        -0.009902
           60-65%          657           0.494523                0.624002        -0.129480
           65-70%          311           0.513158                0.670763        -0.157605
             70%+         1108           0.546544                0.876044        -0.329500

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2223        6.248220        6.081657          0.311392          0.284268
 market     assists           87        2.247106        2.278009          0.338463          0.306331
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          298        7.288379        7.120191          0.333515          0.297686
 market      points          510        5.804358        5.856069          0.304139          0.279955
 market          pr          492        7.377112        6.971620          0.320790          0.293551
 market         pra          493        8.280131        7.870739          0.319040          0.285836
 market          ra          117        3.484947        3.530165          0.305386          0.292622
 market    rebounds          191        2.154150        2.180469          0.246473          0.233415
 market      steals           19        0.837699        2.000540          0.282453          0.260858
 market threes_made           15        0.966594        2.280581          0.230844          0.240759

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
