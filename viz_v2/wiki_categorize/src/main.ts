/*
Copyright 2019 Google Inc.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
    http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

import { bigQueryData } from "./bigQueryData";
import { naturalLanguageApi } from './naturalLanguage';
import { getCategories } from './getWikiCategories';

import * as configFile from './config';
const config = configFile.Config;
const getCats = new getCategories();

const bigquery = new bigQueryData(config);
const naturalLanguage = new naturalLanguageApi(config);

async function getData() {
    const rows = await bigquery.querySourceTable();
    const chunks = chunk(rows, 100);
    processData(chunks, 0);
}

async function processData(chunks, i) {

    await Promise.all(chunks[i].map(async (row) => {
        const page_title = row['page_title'];
        const title = page_title.substring(5);

        const catString = await getCats.getWikiCategories(title);
        if (catString === undefined) {
            bigquery.writeToTable(row, catString);
        } else {
            const categories = await naturalLanguage.getCloudCategory(catString, title);
            bigquery.writeToTable(row, categories);  
        }
       
    })).then(() => {
        console.log(`${i+1} Jobs done: ${chunks[i].length} added`);
        if (i < chunks.length - 1) {
            i++;
            setTimeout(() => processData(chunks, i), 900); 
        } else {
            console.log('All chunks processed');
        }
        
    }).catch(error => console.error('caught', error));
}

const chunk = (arr, size) => 
    arr.reduce((chunks, el, i) => 
    (i % size ? 
        chunks[chunks.length - 1].push(el) : 
        chunks.push([el])) && chunks, []);
        
getData();