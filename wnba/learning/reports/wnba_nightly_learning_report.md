# WNBA Nightly Learning Report

Generated: 2026-07-10T04:25:06Z
Graded predictions in ledger: 2135

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
   rebounds          184 0.633136 2.192624    -0.095073
threes_made           15 0.600000 0.966594    -0.080387
     points          494 0.564050 5.799274    -0.182918
        pra          472 0.535181 8.363724    -0.252230
     steals           19 0.526316 0.837699    -0.234446

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
assists           85 0.474359 2.247392    -0.298005
     pa          281 0.487455 7.350686    -0.267562
     pr          471 0.493534 7.493986    -0.270345
     ra          113 0.495413 3.499279    -0.218374

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
2026-07-07       Azzi Fudd   points under   12.008479             14.0           12.0        0.008479
2026-06-01 Stefanie Dolson rebounds under    2.021912              4.0            2.0        0.021912
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038
2026-06-17  Kayla Thornton   points under    7.972123              9.5            8.0        0.027877
2026-05-08  Julie Allemand rebounds under    2.971458              5.0            3.0        0.028542

## Team Accuracy
team  sample_size  accuracy      mae
 POR          144  0.611511 6.657401
 DAL          131  0.601562 5.080850
 NYL          227  0.566964 6.449234
 GSV          144  0.566434 5.481897
 ATL          119  0.560345 5.322274
 PHX          171  0.547619 7.053012
 LVA          190  0.546448 5.729684
 IND          158  0.522581 6.112581
 MIN          140  0.503704 6.006031
 LAS          159  0.500000 5.983520
 SEA          132  0.500000 5.916537
 WAS           79  0.493506 9.045986

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts            7  0.285714 15.532526
 Georgia Amoore           22  0.227273 14.081145
 Rickea Jackson            9  0.222222 11.036991
  Caitlin Clark           43  0.395349 10.766204
  Natasha Cloud           13  0.461538 10.696878
    Carla Leite           37  0.567568 10.075768
Hailey Van Lith            7  0.428571  9.607210
Sabrina Ionescu           36  0.428571  9.573670
 Brittney Sykes           36  0.400000  9.360317
  Marina Mabrey           44  0.558140  8.686572
   Kiki Iriafen            7  0.000000  8.657472
  Cameron Brink           20  0.333333  8.589116

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          144           0.577465                0.582097        -0.004632
           60-65%          605           0.497453                0.624097        -0.126644
           65-70%          281           0.507299                0.670641        -0.163341
             70%+         1105           0.547135                0.876491        -0.329356

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2135        6.289897        6.108970          0.312997          0.284879
 market     assists           85        2.247392        2.285790          0.336224          0.304127
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          281        7.350686        7.199885          0.332949          0.296384
 market      points          494        5.799274        5.839856          0.304859          0.279354
 market          pr          471        7.493986        7.021510          0.325587          0.296643
 market         pra          472        8.363724        7.946079          0.321134          0.286848
 market          ra          113        3.499279        3.545615          0.306990          0.294759
 market    rebounds          184        2.192624        2.222030          0.248095          0.234414
 market      steals           19        0.837699        2.000540          0.282453          0.260858
 market threes_made           15        0.966594        2.280581          0.230844          0.240759

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
