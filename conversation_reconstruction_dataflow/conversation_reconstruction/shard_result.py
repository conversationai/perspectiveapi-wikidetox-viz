
# -*- coding: utf-8 -*-
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

A dataflow pipeline to shard ingested revisions on Wikipedia talk pages based on the month in the year the revision was created.

Run with:

shard*.sh in helper_shell

"""
from __future__ import absolute_import
import argparse
import logging
import subprocess
import json
from os import path
import urllib2
import traceback
from google.cloud import bigquery as bigquery_op 
import copy
import sys
import datetime

import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions
from apache_beam.options.pipeline_options import SetupOptions
from apache_beam.io.avroio import ReadFromAvro 
from apache_beam.io import filesystems


LOG_INTERVAL = 100
THERESHOLD = 5e9

def run(known_args, pipeline_args):
  """Main entry point; defines and runs the sharding pipeline."""

  pipeline_args.extend([
    '--runner=DataflowRunner',
    '--project=wikidetox-viz',
    '--staging_location=gs://wikidetox-viz-dataflow/staging',
    '--temp_location=gs://wikidetox-viz-dataflow/tmp',
    '--job_name=shard-result',
    '--num_workers=30'])
  pipeline_options = PipelineOptions(pipeline_args)
  pipeline_options.view_as(SetupOptions).save_main_session = True

  time_func = lambda x: datetime.datetime.strptime(json.loads(x)['timestamp'], "%Y-%m-%dT%H:%M:%SZ")
  # Queries extracting the data
  with beam.Pipeline(options=pipeline_options) as p:
       pcoll = (p | beam.io.ReadFromText(known_args.input) 
                 | beam.Map(lambda x: ('{month}at{year}'.format(month=time_func(x).month, year=time_func(x).year), json.loads(x))) 
                 | beam.GroupByKey()
                 | beam.ParDo(WriteToStorage()))

class WriteToStorage(beam.DoFn):
  def start_bundle(self):
    self.outputfile = None
    self.month = None
    self.year = None
    self.sizecnts = 0
    self.filecnts = 0
    self.schema = 'user_id,user_text,timestamp,content,parent_id,replyTo_id,indentation,page_id,page_title,type,id,rev_id,conversation_id,authors'  
    self.fields = self.schema.split(',')
  def clean_schema(self, x):
      res = {}
      for f in self.fields:
          if f in x:
             res[f] = x[f]
          else:
             res[f] = None
      return res

  def process(self, element):
      (key, val) = element
      month, year = [int(x) for x in key.split('at')]
      if not(self.outputfile == None) and self.sizecnts > THERESHOLD:
         self.outputfile.close()
         self.outputfile = None
      if self.outputfile == None or not(year == self.year) or not(month == self.month):
         self.sizecnts = 0  
         self.filecnts = 0
         self.month = month
         self.year = year
         if not(self.outputfile == None):
            self.outputfile.close()
         cnt = 0
         self.path = known_args.output + 'year-{year}/month-{month}/revisions-{index}.json'.format(month=month, year=year, index=cnt)
         while filesystems.FileSystems.exists(self.path):
             cnt += 1
             self.path = known_args.output + 'year-{year}/month-{month}/revisions-{index}.json'.format(month=month, year=year, index=cnt)
         logging.info('USERLOG: Write to path %s.'%self.path)
         self.outputfile = filesystems.FileSystems.create(self.path)
      for output in val:
          output = self.clean_schema(output)
          tmp = json.dumps(output) 
          self.outputfile.write(tmp + '\n')
          self.sizecnts += len(tmp)
          self.filecnts += 1
      logging.info('Number of records %d written to %s.'%(self.filecnts, self.path))
      logging.info('Total length of records %d written to %s.'%(self.sizecnts, self.path))
  def finish_bundle(self):
      if not(self.outputfile == None):
         self.outputfile.close()

if __name__ == '__main__':
  logging.getLogger().setLevel(logging.INFO)
  parser = argparse.ArgumentParser()

  # Input/Output parameters
  parser.add_argument('--input',
                      dest='input',
                      help='Input storage.')
  parser.add_argument('--output',
                      dest='output',
                      help='Output storage.')
  known_args, pipeline_args = parser.parse_known_args()
  run(known_args, pipeline_args)
