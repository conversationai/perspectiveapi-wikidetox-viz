cd ..
python dataflow_main.py --input_table wikidetox_conversations.ingested_test --input_page_state_table wikidetox_conversations.page_states_test --last_revision_table wikidetox_conversations.test_last_revision --page_states_output_table  wikidetox_conversations.page_states_test --category test --week 4 --year 2003 --setup_file setup.py --load_input_from_cloud
