"""
Copyright 2017 Google Inc.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

-------------------------------------------------------------------------------
"""

# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function
from __future__ import unicode_literals
from builtins import *
from future.builtins.disabled import *

import copy
import json
from collections import defaultdict
from noaho import NoAho
import re
import sys
import traceback
import atexit
import os
from .utils.third_party.deltas.tokenizers import text_split
from .utils.third_party.rev_clean import clean
from .utils.diff import diff_tuning
from .utils.third_party.deltas.algorithms import sequence_matcher
from .utils.insert_utils import *
from .utils.actions import *

def insert(rev, page, previous_comments, DEBUGGING_MODE = False):
    """    
       Given the current revision, page state and previously deleted comments.
       This function compares the latest processed revision with the input revision 
       and determine what kind of conversation actions were done to the page. 
       It returns the list of actions and the updated page state.
       
       One main component here is the page state -- page['actions'],
       it's a dictionary with the key as an offset on the page representing a starting position 
       of an action, and the value is a tuple (action_id, indentation).
       The endding offset is also included in the list, with (-1, -1) denoting the boundary of 
       the page.
    """ 
    comment_removals = []
    tmp_rmvs = []
    comment_additions = []
    removed_actions = {}
    old_actions = sorted(page['actions'].keys())
    modification_actions = defaultdict(int)
    rev_text = text_split.tokenize(rev['text'])
    # Process each operation in the diff
    for op in rev['diff']:
        if DEBUGGING_MODE : 
           print(op['name'], op['a1'], op['a2'], op['b1'], op['b2'])
           if 'tokens' in op: print((''.join(op['tokens'])).encode('utf-8'))
        # Ignore parts that remain the same
        if op['name'] == 'equal':
            continue
        if op['name'] == 'insert':
            if op['a1'] in old_actions and (op['tokens'][0].type == 'break' \
                or op['b1'] == 0 or (op['b1'] > 0 and rev_text[op['b1'] - 1].type == 'break')) and \
                (op['b2'] == len(rev_text) or op['tokens'][-1].type == 'break'): 
                    content = "".join(op['tokens'])
                    # If the current insertion is adding a new comment
                    for c in divide_into_section_headings_and_contents(op, content):
                        # Divide the newly added content into headings and contents
                        comment_additions.append(c)
                        if DEBUGGING_MODE:
                           print('COMMENT ADDITIONS:', c['a1'], c['a2'], c['b1'], c['b2'], (''.join(c['tokens'])).encode("utf-8"), len(c['tokens']))
            else:
                # If the current insertion is modifying an existed comment
                old_action_start = get_action_start(old_actions, op['a1'])
                # Find the corresponding existed comment and set a flag
                modification_actions[old_action_start] = True
                

        if op['name'] == 'delete':
            # Deletions may remove multiple comments at the same time
            # Here is to locate the boundary of the deletion in the old revision
            delete_start = op['a1']
            delete_end = op['a2']
            deleted_action_start = find_pos(delete_start, old_actions)
            deleted_action_end = find_pos(delete_end, old_actions)
            deleted_action_end = deleted_action_end + 1 
            start_token = 0 
            # If the deletion removes/modifies existed multiple coments
            # Divide the deletion
            for ind, act in enumerate(old_actions[deleted_action_start:deleted_action_end]):
                if act == delete_end: break
                partial_op = {}
                partial_op['a1'] = max(delete_start, act)
                partial_op['a2'] = min(delete_end, old_actions[deleted_action_start + ind + 1])
                partial_op['b1'] = op['b1']
                partial_op['b2'] = op['b2']
                partial_op['tokens'] = op['tokens'][start_token:partial_op['a2'] - partial_op['a1'] +start_token]
                start_token += partial_op['a2'] - partial_op['a1']
                # Determine if the subset of the deletion is a comment removal of modification
                if delete_start > act or act == old_actions[deleted_action_end - 1] or act in modification_actions:
                    modification_actions[act] = True
                else:
                    tmp_rmvs.append((act, [page['actions'][act], partial_op]))
    # Additions and removals happened to the beginning of a modified comment are hard to detect at the first place
    # Here we go through all the comments being modified and examine if there's addition and removals happened at the head of the modification
    updated_comment_additions = []    
    for action in comment_additions:
        if not(action['a1'] in modification_actions): updated_comment_additions.append(action)
    comment_additions = updated_comment_additions
    for action in tmp_rmvs:
        if not(action[0] in modification_actions):
           comment_removals.append(action[1])
           removed_actions[action[0]] = True
    rearrangement = {}
    updated_removals = []
    end_tokens = []      
    updated_actions = []
    # The comment rearrangements are the comments being removed and added in the same revision
    # Thus we compare the detected removals with additions
    for removal in comment_removals:
        # Removals with too few tokens may not be meaningful sentence
        if len(removal[1]['tokens']) <= 10:
           continue
        removed = ''.join(removal[1]['tokens'])
        rearranged = False
        updated_additions = []
        for ind, insert in enumerate(comment_additions):
            inserted = ''.join(insert['tokens'])
            # Determine if the removed content is part of an addition
            if removed in inserted:
                # Update the rearranagement action
                start_pos = inserted.find(removed)
                start_tok = len(text_split.tokenize(inserted[:start_pos]))
                end_tok = start_tok + len(removal[1]['tokens'])
                end_tokens.append((start_tok + insert['b1'], end_tok + insert['b1']))
                rearrangement[removal[1]['a1']] = start_tok + insert['b1']
                if DEBUGGING_MODE: 
                   print('REARRANGEMENT: ', removal[1]['a1'], start_tok + insert['b1'])
                tmp_ins = []
                # Divide the comment addition
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
                # Update the comment additions 
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
    
    # Until this point, we are sure the comment removal actions we collected are actually removals.    
    # Register removal actions   
    for removal in comment_removals:
        updated_actions.append(comment_removal(removal, rev))
        
    # Update offsets of existed actions in the current revision 
    updated_page = {}
    updated_page['page_id'] = rev['page_id']
    updated_page['actions'] = {}
    updated_page['page_title'] = rev['page_title']
    for act in old_actions:
        if not(act in modification_actions or act in removed_actions):
            # If an action is modified, we locate it later
            # If an action is removed, we ignore it in the updated page state
            new_pos = locate_new_token_pos(act, rev['diff'])
            # Otherwise we try to locate its updated offset position in the current revision 
            if DEBUGGING_MODE and page['actions'][act] == (-1, -1): print(act, new_pos)
            updated_page['actions'][new_pos] = page['actions'][act]
        # If an action is in rearrangement(it will also be in the removed action set) 
        # The updated action should be registered into its newly rearranged location
        if act in rearrangement:
               updated_page['actions'][rearrangement[act]] = page['actions'][act]

    
    # Locate the updated offset of existed actions that were modified in the current revision
    for old_action_start in modification_actions.keys():
        # Locate the old and new starting and ending offset position of the action
        old_action = page['actions'][old_action_start][0]
        old_action_end = get_action_end(old_actions, old_action_start) 
        new_action_start = locate_new_token_pos(old_action_start, rev['diff'], 'left_bound')
        new_action_end = locate_new_token_pos(old_action_end, rev['diff'], 'right_bound')
        # Get the updated text
        tokens = text_split.tokenize(rev['text'])[new_action_start : new_action_end]
        # Create the action modification object and register the new action
        new_action, new_pos, new_id, new_ind = comment_modification(old_action, tokens, new_action_start, new_action_end, rev, updated_page['actions'], old_action_start)
        updated_actions.append(new_action)
        # Update the action on the page state
        updated_page['actions'][new_pos] = (new_action['id'], new_ind)
    updated_additions = []
    # Comment restorations are previouly deleted comments being added back
    # Finding comment restoration
    for insert_op in comment_additions:
        tokens = insert_op['tokens']
        text = ''.join(tokens)
        last_tok = 0
        last_pos = 0
        # We are using a trie to locate substrings of previously deleted comments present in the current addition action
        for k1, k2, val in previous_comments.findall_long(text):
            # If a valid match was found, we'll divide the addition into pieces
            k1_tok = len(text_split.tokenize(text[last_pos:k1])) + last_tok
            last_pos = k2
            k2_tok = min(len(tokens), len(text_split.tokenize(text[k1:k2])) + k1_tok)
            if k1_tok >= k2_tok:
               continue
            last_op = {}
            last_op['tokens'] = tokens[last_tok:k1_tok]
            # For parts that are not a restoration, we add it back to the comment addition set
            if not(last_op['tokens'] == []):
                last_op['a1'] = insert_op['a1']
                last_op['a2'] = insert_op['a2']
                last_op['b1'] = last_tok + insert_op['b1']
                last_op['b2'] = k1_tok + insert_op['b1']
                updated_additions.append(last_op)
            # Create the restoration object and update its offset on page state
            updated_actions.append(comment_restoration(val[0], tokens[k1_tok:k2_tok], k1_tok + insert_op['b1'], rev, insert_op['a1']))
            updated_page['actions'][k1_tok + insert_op['b1']] = val
            end_tokens.append((k1_tok + insert_op['b1'], k2_tok + insert_op['b1']))
            last_tok = k2_tok
            last_pos = k2
            if DEBUGGING_MODE:
               print('restoration:', tokens[k1_tok:k2_tok], k1_tok + insert_op['b1'], k2_tok + insert_op['b1'])

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
    # Until this point, we are sure the comment additions in the list are actually additions
    # Create the addition object and update the offsets on page state
    for insert_op in comment_additions:
        new_action, new_pos, new_id, new_ind = comment_adding(insert_op, rev, updated_page['actions'])
        updated_page['actions'][new_pos] = (new_id, new_ind)
        updated_actions.append(new_action)
        end_tokens.append((insert_op['b1'], insert_op['b2']))
    # For each end position of all actions, we make sure they are registered in the page state
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
                  
    # Sanity checks 
    # The page states must start with 0 and end with the last token as a boundary
    # The value of the page boundary must be (-1, -1)
    # (-1, -1) denotes the page boundary, thus no other positions should have the same value. 
    assert (0 in updated_page['actions'])
    eof = max(list(updated_page['actions'].keys()))
    if DEBUGGING_MODE:
       print(eof)
    for action, val in updated_page['actions'].items():
        if not(action == eof):
           assert not(val == (-1, -1)) 
    assert updated_page['actions'][eof] == (-1, -1)
    
    updated_actions = sorted(updated_actions, key = lambda k: int(k['id'].split('.')[1]))
    return updated_actions, updated_page


class Conversation_Constructor:
    def __init__(self):
        self.page = {}
        self.THERESHOLD = 10 
        # Deleted comments with less than this number of tokens will not be recorded 
        # thus not considered in comment restoration actions to reduce confusion.
        self.conversation_ids = {}
        self.authorship = {}
        self.deleted_comments = []
        self.deleted_records = {}
        self.latest_content = ""
        self.revids = []
        self.NOT_EXISTED = True
           
    def page_creation(self, rev):
        page = {}
        page['page_id'] = rev['page_id']
        page['actions'] = {}
        page['page_title'] = rev['page_title']
        page['actions'][0] = (-1, -1) 
        self.NOT_EXISTED = False 
        return page        

    def load(self, page_state, deleted_comments, conversation_ids, authorship, latest_content):
        """
          Load the previous page state, deleted comments and other information
        """
        self.page = json.loads(page_state)
        self.page['actions'] = {int(key): tuple(val) for key, val in self.page['actions'].items()}
        self.conversation_ids = json.loads(conversation_ids) 
        self.authorship = {action: set([tuple(p) for p in x]) for action, x in json.loads(authorship).items()}
        self.deleted_comments = []
        self.deleted_records = {}
        self.latest_content = clean(latest_content)
        self.previous_comments = NoAho()
        for pair in json.loads(deleted_comments):
            self.previous_comments.add(pair[0], (pair[1], int(pair[2])))
            self.deleted_records[pair[1]] = True
        self.NOT_EXISTED = False 
        return 



    def convert_diff_format(self, x, a, b):
        ret = {}
        ret['name'] = x.name
        ret['a1'] = x.a1
        ret['a2'] = x.a2
        ret['b1'] = x.b1
        ret['b2'] = x.b2
        if x.name == 'insert':
           ret['tokens'] = b[x.b1:x.b2]
        if x.name == 'delete':
           ret['tokens'] = a[x.a1:x.a2]
        return ret 
   
    def clean_dict(self, the_dict):
        """
          We only store the information of currently 'alive' actions.
          Definition of alive: 
             - The action was a deletion happened recently, hence might be restored later.
             - The action is still present on the page, hence might be modified/removed/replied to.
        """
        keylist = the_dict.keys()
        ret = the_dict
        alive_actions = set([action[0] for action in self.page['actions'].values()])
        for action in keylist:
            if not(action in alive_actions or action in self.deleted_records):
               del ret[action]
        return ret
        
    def process(self, rev, DEBUGGING_MODE = False):
        if DEBUGGING_MODE:
           print('REVISION %s'%rev['rev_id'])
        self.revids.append(int(rev['rev_id'])) 
        # Clean the HTML format of the revision
        rev['text'] = clean(rev['text'])
        # Compute the diff between the latest processed revision and the current one
        a = text_split.tokenize(self.latest_content)
        b = text_split.tokenize(rev['text']) 
        rev['diff'] = sorted([self.convert_diff_format(x, a, b) for x in list(sequence_matcher.diff(a, b))], key=lambda k: k['a1'])
        rev['diff'] = diff_tuning(rev['diff'], a, b)
        rev['diff'] = sorted(rev['diff'], key=lambda k: k['a1'])
        # Create a new page if this page was not processed at all before
        if self.NOT_EXISTED:
            self.previous_comments = NoAho()
            old_page = self.page_creation(rev)
        else:    
            old_page = self.page
        self.latest_content = rev['text']
    
        # Process the revision to get the actions and update page state
        actions, updated_page = insert(rev, old_page, self.previous_comments, DEBUGGING_MODE)
        self.page = updated_page
        # Post process of the actions: 
        for action in actions:
            # If the action is adding new content
            # - locate which conversation does it belong to
            # - record the name of the author into the author list of the comment
            if action['type'] == 'COMMENT_ADDING' or action['type'] == 'COMMENT_MODIFICATION' \
               or action['type'] == 'SECTION_CREATION':
               if action['replyTo_id'] == None:
                  self.conversation_ids[action['id']] = action['id']
               else:
                  self.conversation_ids[action['id']] = self.conversation_ids[action['replyTo_id']]
               if action['type'] == 'COMMENT_MODIFICATION':
                  self.authorship[action['id']] = set(self.authorship[action['parent_id']])
                  self.authorship[action['id']].add((action['user_id'], action['user_text']))
               else:
                  self.authorship[action['id']] = set([(action['user_id'], action['user_text'])])
            else:
               self.authorship[action['id']] = set(self.authorship[action['parent_id']])  
            # If a comment was rearranged in an action, the conversation it belongs to might as well get changed.
            if action['type'] == 'COMMENT_REARRANGEMENT':
               if action['replyTo_id'] == None:
                  self.conversation_ids[action['id']] = action['id']
               else:
                  self.conversation_ids[action['id']] = self.conversation_ids[action['replyTo_id']]
            # If a comment is removed or restored, we consider it belongs to the same conversation as its original version.
            if action['type'] == 'COMMENT_REMOVAL':
               self.conversation_ids[action['id']] = self.conversation_ids[action['parent_id']]
            if action['type'] == 'COMMENT_RESTORATION':
               self.conversation_ids[action['id']] = self.conversation_ids[action['parent_id']]
            action['conversation_id'] = self.conversation_ids[action['id']]
            action['authors'] = json.dumps(list(self.authorship[action['id']]))
            action['page_id'] = rev['page_id']
            action['page_title'] = rev['page_title'] 
            # If a comment is deleted, we add it to the recently deleted set for identifying restoration actions later. Note that recently means a time span of at least a week, it can be longer if you have enough memory.
            if action['type'] == 'COMMENT_REMOVAL' and len(action['content']) > self.THERESHOLD:
                self.deleted_comments.append((''.join(action['content']), action['parent_id'], action['indentation']))
                self.deleted_records[action['parent_id']] = True
                self.previous_comments.add(''.join(action['content']), (action['parent_id'], action['indentation']))
        self.conversation_ids = self.clean_dict(self.conversation_ids)
        self.authorship = self.clean_dict(self.authorship)
        # Update the page state
        page_state = {'rev_id': int(rev['rev_id']), \
                      'timestamp': rev['timestamp'], \
                      'page_id': rev['page_id'], \
                      'page_state': json.dumps(self.page), \
                      'deleted_comments': json.dumps(self.deleted_comments), \
                      'conversation_id': json.dumps(self.conversation_ids), \
                      'authors': json.dumps({action_id: list(authors) for action_id, authors in self.authorship.items()})}
        return page_state, actions
