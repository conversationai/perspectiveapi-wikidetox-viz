# Filter out duplicates
#standardSQL
SELECT
  * EXCEPT(row_number)
FROM
(SELECT
    *,
    ROW_NUMBER()
          OVER (PARTITION BY record_id, model) row_number
  FROM
    wikidetox_conversations.scored_comments)
WHERE row_number = 1

# Divide into Two types
SELECT *
FROM wikidetox_conversations.conversations
WHERE type = 'COMMENT_ADDING' or type = 'SECTION_CREATION' or type = 'COMMENT_MODIFICATION'

SELECT *
FROM wikidetox_conversations.conversations
WHERE type = 'COMMENT_REMOVAL' or type = 'COMMENT_RESTORATION'

# Join with the conversations
SELECT *
FROM wikidetox_conversations.conversations_self AS conversations
JOIN wikidetox_conversations.scored_comments as scores
ON conversations.id = scores.record_id
WHERE scores.model = "RockV5_1:TOXICITY"

SELECT *
FROM wikidetox_conversations.conversations_parent AS conversations
JOIN wikidetox_conversations.scored_comments as scores
ON conversations.parent_id = scores.record_id
WHERE scores.model = "RockV5_1:TOXICITY"

SELECT *
FROM wikidetox_conversations.conversation_parent, wikidetox_conversations.conversation_self

# Filter out Partially Scored Conversations
SELECT s.conversations_conversation_id as conversation_id, s.conversations_page_title as page_title,
       s.conversations_indentation as indentation, s.conversations_replyTo_id as replyTo_id,
       s.conversations_id as id, s.conversations_content as content, s.conversations_user_text as user_text, s.conversations_rev_id as rev_id,
       s.conversations_type as type, s.conversations_user_id as user_id, s.conversations_page_id as page_id,
       s.conversations_timestamp as timestamp, s.conversations_parent_id as parent_id, s.scores_score as score
FROM wikidetox_conversations.conversation_with_score as s
JOIN
(SELECT original.conversation_id
FROM
(SELECT *
FROM
(SELECT COUNT(*) as all_len, conversation_id
FROM wikidetox_conversations.conversations
GROUP BY conversation_id) AS original
JOIN
(SELECT COUNT(*) as cur_len, conversations_conversation_id
FROM wikidetox_conversations.conversation_with_score
GROUP BY conversations_conversation_id) AS with_score
ON original.conversation_id = with_score.conversations_conversation_id)
WHERE original.all_len = with_score.cur_len) as pick
ON s.conversations_conversation_id = pick.original.conversation_id


==================================MATCHING STARTS HERE==================================

# Pick out conversations that went bad
SELECT 
  all.id AS id,
  all.score AS score,
  all.conversation_id AS conversation_id,
  all.page_title AS page_title,
  all.indentation AS indentation,
  all.replyTo_id AS replyTo_id,
  all.content AS content,
  all.user_text AS user_text,
  all.rev_id AS rev_id,
  all.type AS type,
  all.user_id AS user_id,
  all.page_id AS page_id,
  all.timestamp AS timestamp,
  all.parent_id AS parent_id,
  attack_time.attack_time AS attack_time
FROM
(SELECT *
FROM wikidetox_conversations.conversation_with_score as all
JOIN
(SELECT min(timestamp) as attack_time, conversation_id
FROM wikidetox_conversations.conversation_with_score
WHERE score > 0.6
GROUP BY conversation_id) as attack_time
ON all.conversation_id = attack_time.conversation_id)
WHERE all.timestamp <= attack_time.attack_time
# DESTINATION TABLE: wikidetox_conversations.6_bad_convs

# Pick out good conversations
SELECT 
  all.id AS id,
  all.score AS score, 
  all.conversation_id AS conversation_id,
  all.page_title AS page_title,
  all.indentation AS indentation,
  all.replyTo_id AS replyTo_id,
  all.content AS content,
  all.user_text AS user_text, 
  all.rev_id AS rev_id,
  all.type AS type,
  all.user_id AS user_id,
  all.page_id AS page_id,
  all.timestamp AS timestamp, 
  all.parent_id AS parent_id
FROM
(SELECT *
FROM wikidetox_conversations.conversation_with_score as all
JOIN
(SELECT max(score) as max_toxicity, conversation_id
FROM wikidetox_conversations.conversation_with_score
GROUP BY conversation_id) as max_score
ON all.conversation_id = max_score.conversation_id)
WHERE max_score.max_toxicity < 0.6
# DESTINATION TABLE: wikidetox_conversations.6_good_convs

# Get Statistics of bad conversation table
SELECT COUNT(*) as length, MIN(timestamp) as start_time, conversation_id, FIRST(page_id) as page_id, MAX(timestamp) as end_time, EXACT COUNT(DISTINCT user_text) as no_users
FROM wikidetox_conversations.6_bad_convs
GROUP BY conversation_id
# DESTINATION TABLE: wikidetox_conversations.6_bad_convs_stats

# Filter out conversations only have attacks or only have one user
SELECT *
FROM wikidetox_conversations.6_bad_convs_stats
WHERE end_time > start_time and no_users > 1
# DESTINATION TABLE: wikidetox_conversations.6_bad_convs_stats


# Get Number of users and max toxicity
SELECT all.length as length, all.start_time as start_time, all.conversation_id as conversation_id, all.page_id as page_id, all.end_time as end_time, all.no_users as no_users,
       before.max_toxicity as max_toxicity, before.no_users_before as no_users_before
FROM wikidetox_conversations.6_bad_convs_stats as all
JOIN
(SELECT MAX(score) as max_toxicity, EXACT COUNT(DISTINCT user_text) as no_users_before, conversation_id
FROM
(SELECT *
FROM wikidetox_conversations.6_bad_convs
WHERE timestamp < attack_time)
GROUP BY conversation_id) as before
ON before.conversation_id == all.conversation_id
# DESTINATION TABLE: wikidetox_conversations.6_bad_convs_stats


# Get Statistics of good conversation table
SELECT COUNT(*) as conversation_length, conversation_id, end_time, FIRST(page_id) as page_id, COUNT(DISTINCT user_text) as no_users, MIN(timestamp) as start_time, MAX(score) as max_toxicity
FROM
(SELECT end_times.timestamp as end_time, all.timestamp as timestamp, end_times.conversation_id as conversation_id, all.page_id as page_id, all.user_text as user_text, all.score as score
FROM wikidetox_conversations.6_good_convs as all
JOIN
(SELECT conversation_id as conversation_id, timestamp
FROM wikidetox_conversations.6_good_convs
GROUP BY conversation_id, timestamp) as end_times
ON all.conversation_id = end_times.conversation_id)
WHERE timestamp <= end_time
GROUP BY conversation_id, end_time
# DESTINATION TABLE: wikidetox_conversations.6_good_convs_stats

# Get number of users and max toxicity in the conversation
SELECT b.no_users_before as no_users_before, b.max_toxicity as max_toxicity, a.conversation_length as length, a.conversation_id as conversation_id,
       a.end_time as end_time, a.page_id as page_id, a.no_users as no_users, a.start_time as start_time
FROM wikidetox_conversations.6_good_convs_stats as a
JOIN
(SELECT COUNT(DISTINCT all.user_text) as no_users_before, MAX(all.score) as max_toxicity, stats.end_time, all.conversation_id
FROM
(SELECT all.score, all.user_text, all.timestamp, stats.end_time, all.conversation_id
FROM wikidetox_conversations.6_good_convs as all
JOIN wikidetox_conversations.6_good_convs_stats as stats
ON all.conversation_id == stats.conversation_id)
WHERE all.timestamp < stats.end_time
GROUP BY all.conversation_id, stats.end_time) as b
ON a.conversation_id == b.all.conversation_id and a.end_time == b.stats.end_time
# DESTINATION TABLE: wikidetox_conversations.6_good_convs_stats

# Get the max toxicity after a certain timepoint
SELECT a.no_users_before as no_users_before, a.max_toxicity as max_toxicity, a.length as length, a.conversation_id as conversation_id,
       a.end_time as end_time, a.page_id as page_id, a.no_users as no_users, a.start_time as start_time,
       b.max_toxicity as max_toxicity_after
FROM wikidetox_conversations.6_good_convs_stats as a
JOIN
(SELECT MAX(all.score) as max_toxicity, stats.end_time, all.conversation_id
FROM
(SELECT all.score, all.user_text, all.timestamp, stats.end_time, all.conversation_id
FROM wikidetox_conversations.6_good_convs as all
JOIN wikidetox_conversations.6_good_convs_stats as stats
ON all.conversation_id == stats.conversation_id)
WHERE all.timestamp >= stats.end_time
GROUP BY all.conversation_id, stats.end_time) as b
ON a.conversation_id == b.all.conversation_id and a.end_time == b.stats.end_time
# DESTINATION TABLE: wikidetox_conversations.6_good_convs_stats

# Filter out conversations fewer than one comment
SELECT * 
FROM wikidetox_conversations.6_good_convs_stats
WHERE end_time > start_time
# DESTINATION TABLE: wikidetox_conversations.6_good_convs_stats


# Filter out conversations with not so unhealthy end
SELECT *
FROM wikidetox_conversations.6_good_convs_stats
WHERE max_toxicity_after < 0.4
# DESTINATION TABLE: wikidetox_conversations.6_good_convs_stats

# Last commentator in good conv
SELECT *
FROM wikidetox_conversations.6_good_convs_stats
WHERE no_users_before == no_users
# DESTINATION TABLE: wikidetox_conversations.attacker_in_conv_6_good_convs_stats

# Attacker must be in the conversation before
SELECT *
FROM wikidetox_conversations.6_bad_convs_stats
WHERE no_users == no_users_before
# DESTINATION TABLE: wikidetox_conversations.attacker_in_conv_6_bad_convs_stats

# Match conversations on page_id and length
SELECT *
FROM
(SELECT *, ABS(TIMESTAMP_TO_SEC(good.start_time) - TIMESTAMP_TO_SEC(bad.start_time)) as start_time_delta, 
      ABS(TIMESTAMP_TO_SEC(good.end_time) - TIMESTAMP_TO_SEC(bad.end_time)) as end_time_delta,
      ABS(bad.max_toxicity - good.max_toxicity) as toxicity_delta,
      ABS(bad.no_users_before - good.no_users_before) as no_users_delta
FROM wikidetox_conversations.attacker_in_conv_6_bad_convs_stats as bad
JOIN wikidetox_conversations.attacker_in_conv_6_good_convs_stats as good
ON good.page_id == bad.page_id)
WHERE good.length == bad.length
# DESTINATION TABLE: wikidetox_conversations.attacker_in_conv_6_6_cutoff_matched_convs

# Hard constraint on toxicity gap
SELECT *
FROM wikidetox_conversations.attacker_in_conv_6_6_cutoff_matched_convs
WHERE toxicity_delta < 0.1
# DESTINATION TABLE: wikidetox_conversations.attacker_in_conv_6_6_cutoff_matched_convs

# Delete Match Duplicates
#standardSQL
SELECT
  * EXCEPT(row_number)
FROM
(SELECT
    *,
    ROW_NUMBER()
          OVER (PARTITION BY good_conversation_id ORDER BY no_users_delta, start_time_delta, end_time_delta) row_number
  FROM
    wikidetox_conversations.attacker_in_conv_6_6_cutoff_matched_convs)
WHERE row_number = 1
# DESTINATION TABLE: wikidetox_conversations.attacker_in_conv_6_6_cutoff_matched_convs

#standardSQL
SELECT
  * EXCEPT(row_number)
FROM
(SELECT
    *,
    ROW_NUMBER()
          OVER (PARTITION BY bad_conversation_id ORDER BY no_users_delta, start_time_delta, end_time_delta) row_number
  FROM
    wikidetox_conversations.attacker_in_conv_6_6_cutoff_matched_convs)
WHERE row_number = 1
# DESTINATION TABLE: wikidetox_conversations.attacker_in_conv_6_6_cutoff_matched_convs

# Picking out matched bad conversation contents
SELECT all.id as id, all.score as score, all.conversation_id as conversation_id, all.page_title as page_title,
       all.indentation as indentation, all.replyTo_id as replyTo_id, all.content as content,
       all.user_text as user_text, all.rev_id as rev_id, all.type as comment_type,
       all.user_id as user_id, all.page_id as page_id, all.timestamp as timestamp,
       all.parent_id as parent_id, all.attack_time as end_time,
       match.good_conversation_id as good_conversation_id
FROM wikidetox_conversations.6_bad_convs as all
JOIN wikidetox_conversations.attacker_in_conv_6_6_cutoff_matched_convs as match
ON all.conversation_id = match.bad_conversation_id

# Picking out matched good conversation contents
SELECT all.id as id, all.score as score, all.conversation_id as conversation_id, all.page_title as page_title,
       all.indentation as indentation, all.replyTo_id as replyTo_id, all.content as content,
       all.user_text as user_text, all.rev_id as rev_id, all.type as comment_type,
       all.user_id as user_id, all.page_id as page_id, all.timestamp as timestamp,
       all.parent_id as parent_id,
       match.bad_conversation_id as bad_conversation_id,
       match.bad_length as bad_length,
       match.good_end_time as end_time
FROM wikidetox_conversations.6_good_convs as all
JOIN wikidetox_conversations.attacker_in_conv_6_6_cutoff_matched_convs as match
ON all.conversation_id = match.good_conversation_id

SELECT *
FROM wikidetox_conversations.matched_good
WHERE timestamp < end_time
