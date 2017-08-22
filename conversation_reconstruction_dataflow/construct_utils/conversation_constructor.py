from __future__ import absolute_import, division, print_function
from builtins import *
from future.builtins.disabled import *
import copy
import json
from .utils.tokenizers import text_split
from collections import defaultdict
from noaho import NoAho
import re
import sys
import traceback
import atexit
import os
from .utils.rev_clean import clean
from .utils.diff import diff
from .utils.insert_utils import *
from .utils.actions import *

def insert(rev, page, previous_comments, DEBUGGING_MODE = False):

    # devide ins and dels
    # ideas:
        # types of dels: 1) remove a previous action 2) remove in the middle of an action
        # types of ins : 1) add after an action 2) add inside a comment
        # for each action, find the ins and dels corresponding to the action
            # types: 1) full removal
            #        2) add after the action
            #            a) started a newline -- addition
            #            b) if not -- modification
            #        3) modification
            #        4) ins and dels matching(later)

    comment_removals = []
    comment_additions = []
    removed_actions = {}
    old_actions = sorted(page['actions'].keys())
    modification_actions = defaultdict(int)
    rev_text = text_split.tokenize(rev['text'])
    for op in rev['diff']:
        if DEBUGGING_MODE :
           print(op['name'], op['a1'], op['a2'], op['b1'], op['b2'])
           if 'tokens' in op: print(''.join(op['tokens']))
        if op['name'] == 'equal':
            continue

        if op['name'] == 'insert':
            if op['a1'] in old_actions and (op['tokens'][0].type == 'break' \
                or op['a1'] == 0 or rev_text[op['b1'] - 1].type == 'break'):
                    content = "".join(op['tokens'])
                    for c in divide_into_section_headings_and_contents(op, content):
                        comment_additions.append(c)
                        if DEBUGGING_MODE:
                           print(c['name'], c['a1'], c['a2'], c['b1'], c['b2'], ''.join(c['tokens']))
            else:
                old_action_start = get_action_start(old_actions, op['a1'])
                modification_actions[old_action_start] = True

        if op['name'] == 'delete':
            delete_start = op['a1']
            delete_end = op['a2']
            deleted_action_start = find_pos(delete_start, old_actions)
            deleted_action_end = find_pos(delete_end, old_actions)
            deleted_action_end = deleted_action_end + 1
            start_token = 0
            for ind, act in enumerate(old_actions[deleted_action_start:deleted_action_end]):
                if act == delete_end: break
                partial_op = {}
                partial_op['a1'] = max(delete_start, act)
                partial_op['a2'] = min(delete_end, old_actions[deleted_action_start + ind + 1])
                partial_op['b1'] = op['b1']
                partial_op['b2'] = op['b2']
                partial_op['tokens'] = op['tokens'][start_token:partial_op['a2'] - partial_op['a1'] +start_token]
                start_token += partial_op['a2'] - partial_op['a1']
                if delete_start > act or act == old_actions[deleted_action_end - 1]:
                    modification_actions[act] = True
                else:
                    comment_removals.append([page['actions'][act], partial_op])
                    removed_actions[act] = True

    rearrangement = {}
    updated_removals = []
    end_tokens = []
    updated_actions = []
    # Finding comment rearrangements
    for removal in comment_removals:
        removed = ''.join(removal[1]['tokens'])
        rearranged = False
        updated_additions = []
        for ind, insert in enumerate(comment_additions):
            inserted = ''.join(insert['tokens'])
            if removed in inserted:
                start_pos = inserted.find(removed)
                start_tok = len(text_split.tokenize(inserted[:start_pos]))
                end_tok = start_tok + len(removal[1]['tokens'])
                end_tokens.append((start_tok + insert['b1'], end_tok + insert['b1']))
                rearrangement[removal[1]['a1']] = start_tok + insert['b1']
                updated_actions.append(comment_rearrangement(removal[0][0], removal[1]['tokens'], start_tok, rev, insert['a1']))
                tmp_ins = []
                if not(start_tok == 0):
                    tmp_in = copy.deepcopy(insert)
                    tmp_in['b2'] = start_tok + insert['b1']
                    tmp_in['tokens'] = insert['tokens'][:start_tok]
                    tmp_ins.append(tmp_in)
                if not(end_tok == len(insert['tokens'])):
                    tmp_in = copy.deepcopy(insert)
                    tmp_in['b1'] = end_tok + insert['b1']
                    tmp_in['tokens'] = insert['tokens'][end_tok:]
                    tmp_ins.append(tmp_in)
                for tmp_in in tmp_ins:
                    updated_additions.append(tmp_in)
                for tmp_in in comment_additions[ind + 1:]:
                    updated_additions.append(tmp_in)
                rearranged = True
                break
            updated_additions.append(insert)
        if not(rearranged):
            updated_removals.append(removal)
        else:
            comment_additions = updated_additions
    comment_removals = updated_removals

    # Register new actions
    for removal in comment_removals:
        updated_actions.append(comment_removal(removal, rev))

    # Update actions on page
    updated_page = {}
    updated_page['page_id'] = rev['page_id']
    updated_page['actions'] = {}
    updated_page['page_title'] = rev['page_title']
    for act in old_actions:
        if not(act in modification_actions or act in removed_actions):
            new_pos = locate_new_token_pos(act, rev['diff'])
            if DEBUGGING_MODE and page['actions'][act] == (-1, -1): print(act, new_pos)
            updated_page['actions'][new_pos] = page['actions'][act]
        if act in rearrangement:
            updated_page['actions'][rearrangement[act]] = page['actions'][act]

    for old_action_start in modification_actions.keys():
        old_action_end = modification_actions[old_action_start]
        old_action = page['actions'][old_action_start][0]
        old_action_end = get_action_end(old_actions, old_action_start)
        new_action_start = locate_new_token_pos(old_action_start, rev['diff'], 'left_bound')
        new_action_end = locate_new_token_pos(old_action_end, rev['diff'], 'right_bound')
        tokens = text_split.tokenize(rev['text'])[new_action_start : new_action_end]
        new_action, new_pos, new_id, new_ind = comment_modification(old_action, tokens, new_action_start, new_action_end, rev, updated_page['actions'], old_action_start)
        updated_actions.append(new_action)
        updated_page['actions'][new_pos] = (new_action['id'], new_ind)
    updated_additions = []
    # Finding comment restoration
    for insert_op in comment_additions:
        tokens = insert_op['tokens']
        text = ''.join(tokens)
        last_tok = 0
        last_pos = 0
        for k1, k2, val in previous_comments.findall_long(text):
            k1_tok = len(text_split.tokenize(text[last_pos:k1])) + last_tok
            last_pos = k2
            k2_tok = len(text_split.tokenize(text[k1:k2])) + k1_tok
            last_op = {}
            last_op['tokens'] = tokens[last_tok:k1_tok]
            if not(last_op['tokens'] == []):
                last_op['a1'] = insert_op['a1']
                last_op['a2'] = insert_op['a2']
                last_op['b1'] = last_tok + insert_op['b1']
                last_op['b2'] = k1_tok + insert_op['b1']
                updated_additions.append(last_op)
        #   print(k1_tok + insert_op['b1'], k2_tok + insert_op['b1'], text[k1:k2], len(text_split.tokenize(text[k1:k2])))
            updated_actions.append(comment_restoration(val[0], tokens[k1_tok:k2_tok], k1_tok + insert_op['b1'], rev, insert_op['a1']))
            updated_page['actions'][k1_tok + insert_op['b1']] = val
            end_tokens.append((k1_tok + insert_op['b1'], k2_tok + insert_op['b1']))
   #         if DEBUGGING_MODE:
   #            print(k1_tok + insert_op['b1'], k2_tok + insert_op['b1'])
            last_tok = k2_tok
            last_pos = k2
        last_op = {}
        last_op['a1'] = insert_op['a1']
        last_op['a2'] = insert_op['a2']
        last_op['b1'] = last_tok + insert_op['b1']
        last_op['b2'] = insert_op['b2']
        if DEBUGGING_MODE:
           print(last_op, insert_op['b2'])

        if last_op['b2'] - last_op['b1'] > 0:
            last_op['tokens'] = insert_op['tokens'][last_tok:]
            updated_additions.append(last_op)
    comment_additions = updated_additions
    for insert_op in comment_additions:
        new_action, new_pos, new_id, new_ind = comment_adding(insert_op, rev, updated_page['actions'])
        updated_page['actions'][new_pos] = (new_id, new_ind)
        updated_actions.append(new_action)
        end_tokens.append((insert_op['b1'], insert_op['b2']))

    for start_tok, end_tok in end_tokens:
        if not(end_tok in updated_page['actions']):
            tmp_lst = sorted(list(updated_page['actions'].keys()))
            last_rev = tmp_lst[find_pos(start_tok, tmp_lst) - 1]
            if DEBUGGING_MODE:
               print(start_tok, end_tok)
            updated_page['actions'][end_tok] = updated_page['actions'][last_rev]
    if DEBUGGING_MODE:
       print(updated_page['actions'])

    if DEBUGGING_MODE:
        print([(action['type'] , action['id'])for action in updated_actions])

    # Error checking
    assert (0 in updated_page['actions'])
    eof = max(list(updated_page['actions'].keys()))
    if DEBUGGING_MODE:
       print(eof)
    assert updated_page['actions'][eof] == (-1, -1)


    return updated_actions, updated_page


class Conversation_Constructor:
    def __init__(self, COMMENT_TRACKING_FILE = None):
        self.pages = {}
        self.THERESHOLD = 3
        self.previous_comments = {}
        self.latest_content = defaultdict(str)
        if not(COMMENT_TRACKING_FILE == None):
            self.tracking_file = open(COMMENT_TRACKING_FILE, "w")
        else:
            self.tracking_file = None

    def save(self, FILENAME):
        BASE_DIR = 'json_dumps'
        with open(os.path.join(BASE_DIR, FILENAME), "w") as w:
            json.dump([self.pages, self.THERESHOLD, self.latest_content], w)

    def load(self, FILENAME, COMMENT_TRACKING_FILE = None):
        BASE_DIR = 'json_dumps'
        with open(os.path.join(BASE_DIR, FILENAME)) as f:
            self.pages, self.THERESHOLD, self.latest_content = json.load(f)
        self.previous_comments = {}
        for pid in self.pages.keys():
            print(type(pid))
            self.previous_comments[pid] = NoAho()
            updated_actions = {}
            for act, val in self.pages[pid]['actions'].items():
                updated_actions[int(act)] = tuple(val)
            self.pages[pid]['actions'] = updated_actions
            print(updated_actions)
        if not(COMMENT_TRACKING_FILE == None):
            with open(COMMENT_TRACKING_FILE, "r") as f:
                for line in f:
                    pid, key, val = json.loads(line)
                self.previous_comments[pid].add(key, val)
            self.trakcing_file = open(COMMENT_TRACKING_FILE, "a")
        else:
            self.tracking_file = None

    def page_creation(self, rev):
        op = rev['diff'][0]
        page = {}
        page['page_id'] = rev['page_id']
        page['actions'] = {}
        page['page_title'] = rev['page_title']
        page['actions'][0] = (-1, -1) # boundary of the page

        return page


    def process(self, rev, DEBUGGING_MODE = False):
        rev['text'] = clean(rev['text'])
        #print(rev['text'])
        pid = rev['page_id']
        rev['diff'] = list(diff(self.latest_content[pid], rev['text']))
        if pid not in self.pages:
            self.previous_comments[pid] = NoAho()
            self.latest_content[pid] = ""
            updated_page = self.page_creation(rev)
            old_page = updated_page
        else:
            old_page = self.pages[rev['page_id']]


        self.latest_content[pid] = rev['text']

        actions, updated_page = insert(rev, old_page, self.previous_comments[pid], DEBUGGING_MODE)

        self.pages[pid] = updated_page
        for action in actions:
            action['page_id'] = pid
            action['page_title'] = rev['page_title']
            if action['type'] == 'COMMENT_REMOVAL' and len(action['content']) > self.THERESHOLD:
                self.previous_comments[pid].add(''.join(action['content']), (action['parent_id'], action['indentation']))
                if not(self.tracking_file == None):
                    self.tracking_file.write(json.dumps([pid, ''.join(action['content']), (action['parent_id'], action['indentation'])]) + '\n')
        return actions

    def cleanup(self):
        if not(self.tracking_file == None):
            self.tracking_file.close()

