# WNBA Pick Direction Diagnostics

## Side Recommendations
     market  market_sample_size  market_win_rate  recommended_min_edge    allowed_side  suppress_market                        confidence_penalty_rule
    assists                  70         0.492063                   1.0      under_only             True cap_confidence_at_60; penalize_disallowed_side
         pa                 205         0.463054                   3.0 suppress_market             True cap_confidence_at_60; penalize_disallowed_side
     points                 345         0.550296                   5.0      allow_both            False                                               
         pr                 335         0.549849                   5.0      allow_both            False                                               
        pra                 325         0.555556                   5.0      under_only            False                       penalize_disallowed_side
         ra                  75         0.547945                   0.0      under_only            False                       penalize_disallowed_side
   rebounds                 127         0.666667                   1.5      allow_both            False                                               
     steals                  14         0.500000                   0.0      allow_both            False                                               
threes_made                  10         0.600000                   0.0      allow_both            False                                               

## Weak Market Sides
 market  side  sample_size  win_rate  avg_abs_projection_edge  closer_but_wrong_side_rate
     ra  over           23  0.391304                 1.883792                         0.0
assists  over           28  0.440000                 1.318857                         0.0
     pa  over           52  0.450980                 5.344797                         0.0
    pra  over           80  0.462500                 5.762505                         0.0
     pa under          153  0.467105                 4.786800                         0.0

## Closer But Wrong Side
     market  sample_size  win_rate  closer_but_wrong_side_rate  avg_abs_projection_edge
     points          345  0.550296                    0.002899                 3.703642
    assists           70  0.492063                    0.000000                 1.602653
         pa          205  0.463054                    0.000000                 4.928341
         pr          335  0.549849                    0.000000                 5.233723
        pra          325  0.555556                    0.000000                 6.606669
         ra           75  0.547945                    0.000000                 2.128750
   rebounds          127  0.666667                    0.000000                 1.381656
     steals           14  0.500000                    0.000000                 0.512650
threes_made           10  0.600000                    0.000000                 0.493467

## Edge Bucket Diagnostics
 market edge_bucket  sample_size  win_rate  avg_abs_projection_edge
assists       0.5-1           18  0.333333                 0.701781
assists       1-1.5           18  0.625000                 1.219115
assists       1.5-2           12  0.454545                 1.773370
assists         2-3           12  0.416667                 2.255911
assists       0-0.5            6  0.500000                 0.382153
assists         3-5            2  1.000000                 3.885000
assists          5+            2  1.000000                 9.597635
     pa          5+           85  0.488095                 8.221746
     pa         3-5           45  0.533333                 3.851896
     pa         2-3           38  0.289474                 2.394814
     pa       1.5-2           15  0.533333                 1.769554
     pa       1-1.5           12  0.545455                 1.229692
     pa       0.5-1            7  0.142857                 0.795805
     pa       0-0.5            3  1.000000                 0.084314
 points         3-5          102  0.530612                 3.908531
 points          5+           83  0.580247                 7.065175
 points         2-3           74  0.486486                 2.518398
 points       1.5-2           38  0.605263                 1.728188
 points       1-1.5           21  0.600000                 1.222210
 points       0-0.5           14  0.642857                 0.362974
 points       0.5-1           13  0.538462                 0.761250
     pr          5+          166  0.584337                 7.633848
     pr         3-5           81  0.474359                 3.856598
     pr         2-3           47  0.521739                 2.584165
     pr       1.5-2           19  0.526316                 1.698723
     pr       1-1.5            9  0.444444                 1.374050
     pr       0.5-1            8  0.750000                 0.731904
     pr       0-0.5            5  0.800000                 0.348138
    pra          5+          207  0.558252                 8.745764
    pra         3-5           60  0.550000                 3.755375

## Line Movement Coverage
  market line_move_bucket  sample_size  win_rate  line_move_coverage  avg_line_move
 assists          missing           61  0.481481                 0.0            NaN
 assists             flat            9  0.555556                 1.0       0.000000
      pa          missing          162  0.518750                 0.0            NaN
      pa             flat           31  0.258065                 1.0       0.000000
      pa         moved_up            8  0.250000                 1.0       0.812500
      pa    moved_down_1+            2  0.500000                 1.0      -1.000000
      pa      moved_up_1+            2  0.000000                 1.0       1.750000
  points          missing          274  0.559701                 0.0            NaN
  points             flat           48  0.553191                 1.0       0.000000
  points         moved_up           12  0.416667                 1.0       0.625000
  points       moved_down            7  0.428571                 1.0      -0.500000
  points    moved_down_1+            2  0.500000                 1.0      -1.000000
  points      moved_up_1+            2  0.500000                 1.0       2.500000
      pr          missing          268  0.563910                 0.0            NaN
      pr             flat           44  0.488372                 1.0       0.000000
      pr         moved_up           15  0.533333                 1.0       0.733333
      pr       moved_down            4  0.333333                 1.0      -0.500000
      pr    moved_down_1+            2  0.500000                 1.0      -1.500000
      pr      moved_up_1+            2  0.500000                 1.0       2.500000
     pra          missing          275  0.562044                 0.0            NaN
     pra             flat           38  0.552632                 1.0       0.000000
     pra         moved_up            5  0.800000                 1.0       0.600000
     pra      moved_up_1+            5  0.200000                 1.0       2.200000
     pra       moved_down            1  0.000000                 1.0      -0.500000
     pra    moved_down_1+            1  0.000000                 1.0      -3.000000
      ra          missing           56  0.509091                 0.0            NaN
      ra             flat           15  0.666667                 1.0       0.000000
      ra         moved_up            4  0.666667                 1.0       0.750000
rebounds          missing           90  0.697674                 0.0            NaN
rebounds             flat           27  0.636364                 1.0       0.000000
