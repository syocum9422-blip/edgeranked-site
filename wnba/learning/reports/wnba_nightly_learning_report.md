# WNBA Nightly Learning Report

Generated: 2026-08-08T04:25:07Z
Graded predictions in ledger: 2973

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
     steals           27 0.629630 0.799833    -0.094961
   rebounds          271 0.617530 2.187189    -0.081505
threes_made           17 0.588235 1.033154    -0.085047
     points          648 0.553292 5.720951    -0.166567
        pra          672 0.520301 8.197495    -0.224351

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
     ra          173 0.469880 3.671464    -0.214835
     pr          650 0.499220 7.476874    -0.230502
assists           99 0.500000 2.156516    -0.251887
     pa          415 0.506083 6.757484    -0.211130

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
2026-08-03 Sabrina Ionescu       pr under   20.016152             24.5           20.0        0.016152
2026-06-01 Stefanie Dolson rebounds under    2.021912              4.0            2.0        0.021912
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052

## Team Accuracy
team  sample_size  accuracy      mae
 POR          201  0.635897 6.055494
 DAL          187  0.581522 5.570861
 PHX          240  0.564103 6.477495
 LVA          239  0.545455 6.058677
 ATL          191  0.545455 5.620127
 GSV          183  0.543956 5.219245
 MIN          199  0.541237 5.889278
 NYL          284  0.525000 6.446367
 IND          221  0.516129 6.439168
 SEA          178  0.514451 6.003738
 CHI          152  0.496599 5.965609
 LAS          211  0.487923 5.788174

## Player Outliers
          player  sample_size  accuracy       mae
Napheesa Collier           10  0.800000 13.487427
  Rickea Jackson            9  0.222222 11.036991
  Georgia Amoore           30  0.366667 11.003214
    Lauren Betts           11  0.454545 10.915219
   Caitlin Clark           57  0.421053 10.725126
 Sabrina Ionescu           53  0.403846  9.691990
 Hailey Van Lith            7  0.428571  9.607210
  Brittney Sykes           36  0.400000  9.360317
   Marina Mabrey           48  0.595745  9.007011
      Awak Kuier            5  0.600000  8.677498
 Chennedy Carter           18  0.277778  8.511355
    Jackie Young           55  0.431373  8.438629

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          234           0.572052                0.583415        -0.011363
           60-65%         1117           0.503670                0.623624        -0.119954
           65-70%          446           0.501144                0.671466        -0.170322
             70%+         1176           0.549870                0.867690        -0.317820

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2973        6.176138        6.021967          0.299087          0.279679
 market     assists           99        2.156516        2.183502          0.322744          0.294989
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          415        6.757484        6.657925          0.309536          0.284004
 market      points          648        5.720951        5.752455          0.295316          0.277235
 market          pr          650        7.476874        7.069981          0.308950          0.288615
 market         pra          672        8.197495        7.848838          0.306926          0.284335
 market          ra          173        3.671464        3.702136          0.298103          0.290720
 market    rebounds          271        2.187189        2.226923          0.246179          0.237053
 market      steals           27        0.799833        1.625770          0.246704          0.237043
 market threes_made           17        1.033154        2.226334          0.234791          0.244979

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
