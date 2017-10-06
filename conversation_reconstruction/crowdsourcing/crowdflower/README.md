# Crowd-Sourcing Tools

This directory contains some tools to support Crowd Sourcing using CrowdFlower. In particular, some JavaScript to allow a prettier layout of the conversation structure.

## Setup

This is a standard nodejs/yarn project. You need to have installed
`npm` and `node` (Recommended to install using [nvm](https://github.com/creationix/nvm), the node version manager).

Once you have `npm`, install `yarn` and `typescript` globally with:

```shell
npm install -g yarn typescript
```

Then, from this directory, you can setup the this node package with:

```shell
yarn install
```

Link the `wpconvlib` directory into the `node_modules` so it is treated as a node module.

```shell
cd node_modules
ln -s ../../wpconvlib ./
cd ..
```

You may also need to make sure that library is built with:

```
cd ../wpconvlib/
tsc
cd ../crowdflower
```

## Build for CrowdFlower and Local tests

Crowdflower has a special jquery setup, so its different for testing locally than when run in crowdflower. The difference is between concatenating these two files after the generated `app.js` (which has the main part of the code):

* src/jquery_crowdflower_require_hack.js
* src/jquery_localtest_require_hack.js

### Build for crowdflower

```shell
yarn run build:crowdflower
```

Generated files end up in `build/dist/crowdflower.js`. This is what should be copied to the crowdflower JS text box.

## Test Locally

```shell
yarn run build:localtest
```

Generated files end up in `build/dist/localtest.js`.

```shell
yarn run serve:localtest
```

In your browser, then open the URL for the corresponding crowdsourcing job i.e.:

*  http://localhost:8000/src/testdata/test1.html
*  http://localhost:8000/src/testdata/test2.html

And observe the test conversations look right, and that no errors appear in the
JavaScript console.

## Deploy to CrowdFlower

CrowdFlower has 3 sections that need files from this directory need to be copied to the relevant UI input boxes in a CrowdFlower's Job page (afer you run the build command):

* CML: `src/cml{N}.html`
* CSS: `src/style{N}.css`
* JavaScript: `build/dist/crowdflower.js`

Where `{N}` is the corresponding crowdsourcing job.

## Job 1: Conversation Selection Method: ask questions.

TODO(ldixon): update.

Bad:
 - First N comments are OK (score <0.6)
 - N+1 comment (by time) has score > 0.6
 - Conversation = first N comments.

Good:
 - Contains: all comments in a conv (by section)
 - Such that: all comments score < 0.4

Good and bad are matched:
 - Iterate over bad conv to find a match.
   - Good conv happenning on the same page.
   - Good conv must be >= bad conv size.
   - Select the closest good conv in time (choose the closest good conv, w.r.t. point in time to the bad conv)
   - Select fragment of good conv to match the bad conv in size.
 - Each conv only appears once (remove from bucket as we match them)

## Job 2: Conversation Selection Method: Ask on Tail of comments about is there a toxic comment.

TODO(ldixon): write and update.