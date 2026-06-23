# WNBA Nightly Learning Report

Generated: 2026-06-23T04:25:05Z
Graded predictions in ledger: 1590

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
   rebounds          134 0.669355 2.169274    -0.082208
threes_made           10 0.600000 0.951522    -0.126266
     points          370 0.569061 5.880762    -0.206987
        pra          344 0.562682 8.223977    -0.266260
         ra           80 0.545455 3.503860    -0.197302

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
     pa          210 0.466346 7.652078    -0.321341
assists           72 0.476923 2.159916    -0.317064
 steals           15 0.533333 0.845517    -0.232939
     pr          355 0.544160 7.114602    -0.258641
     ra           80 0.545455 3.503860    -0.197302

## Biggest Misses
      date          player market  side  projection  sportsbook_line  actual_result  absolute_error
2026-05-28 Jessica Shepard    pra under   18.114103             25.5           52.0       33.885897
2026-05-28 Jessica Shepard    pra under   18.114103             26.5           52.0       33.885897
2026-06-13  Kahleah Copper    pra under   21.068592             22.5           52.0       30.931408
2026-05-23  Natasha Howard    pra under   16.977403             25.5           45.0       28.022597
2026-05-08    Lauren Betts    pra  over   32.269204             19.5            6.0       26.269204
2026-06-13  Kahleah Copper points under   15.676144             18.5           41.0       25.323856
2026-06-13  Kahleah Copper points under   15.756509             17.5           41.0       25.243491
2026-05-08    Lauren Betts    pra  over   31.167237             18.5            6.0       25.167237
2026-05-23  Natasha Howard     pr under   14.842398             22.5           40.0       25.157602
2026-05-27   Nyara Sabally points under    4.129534              8.5           29.0       24.870466

## Biggest Hits
      date          player   market  side  projection  sportsbook_line  actual_result  absolute_error
2026-05-13 Kelsey Mitchell   steals  over    1.003325              0.5            1.0        0.003325
2026-05-09  Kahleah Copper      pra under   15.004984             23.5           15.0        0.004984
2026-06-01 Stefanie Dolson rebounds under    2.021912              4.0            2.0        0.021912
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038
2026-06-17  Kayla Thornton   points under    7.972123              9.5            8.0        0.027877
2026-05-08  Julie Allemand rebounds under    2.971458              5.0            3.0        0.028542
2026-06-02 Veronica Burton       ra  over   11.968482              9.5           12.0        0.031518
2026-05-10   Saniya Rivers  assists under    2.967019              5.0            3.0        0.032981

## Team Accuracy
team  sample_size  accuracy      mae
 POR          111  0.669725 6.721727
 NYL          153  0.620000 6.504132
 DAL          111  0.614679 5.264993
 IND          109  0.560748 5.321707
 GSV          103  0.558824 5.527237
 PHX          135  0.552239 7.414418
 SEA           98  0.547368 5.036511
 LVA          126  0.541667 6.127884
 MIN          109  0.528846 5.422643
 ATL           96  0.526882 5.528613
 CON           86  0.517647 5.788593
 LAS          112  0.504587 5.815280

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts            6  0.333333 17.189038
 Georgia Amoore           19  0.157895 15.360798
  Natasha Cloud            8  0.250000 14.273418
 Rickea Jackson            9  0.222222 11.036991
Sabrina Ionescu           14  0.384615 10.750356
Chennedy Carter           11  0.363636 10.643571
    Leila Lacan            5  0.200000 10.351339
 Janelle Salaun            5  0.000000 10.123911
    Carla Leite           32  0.593750  9.952199
Hailey Van Lith            7  0.428571  9.607210
 Kahleah Copper           36  0.628571  9.413411
 Brittney Sykes           36  0.400000  9.360317

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%           95           0.612903                0.581609         0.031294
           60-65%          369           0.502762                0.622976        -0.120213
           65-70%          145           0.528571                0.671562        -0.142991
             70%+          981           0.566667                0.893220        -0.326553

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         1590        6.217770        6.082488          0.319548          0.282807
 market     assists           72        2.159916        2.213416          0.342925          0.305450
 market          pa          210        7.652078        7.519126          0.354466          0.307778
 market      points          370        5.880762        5.912353          0.315509          0.282657
 market          pr          355        7.114602        6.829943          0.326425          0.286621
 market         pra          344        8.223977        7.809158          0.327116          0.280633
 market          ra           80        3.503860        3.609064          0.305812          0.290244
 market    rebounds          134        2.169274        2.221240          0.244161          0.227903
 market      steals           15        0.845517        1.995898          0.258702          0.254676
 market threes_made           10        0.951522        1.791287          0.218406          0.228135

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
