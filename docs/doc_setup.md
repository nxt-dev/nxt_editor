# To Deploy Docs

To deploy a total package updated docs build:

1. activate into api docs environment `nxtdocs`

2. run `build/api_docs.nxt`  at the start point `/deploy` to put a build of the api docs into the user docs

3. activate into user docs environment `nxtuserdocs`

4. `cd` to `nxt/docs/user_docs`

5. use `mkdocs gh-deploy` to deploy your full docs to gh-pages branch.

6. Clean up after yourself. `git clean -f -d`

For greater details on either the user or api docs, see [user_docs.md](user_docs/user_docs.md), and [api_docs.md](api_docs/api_docs.md)
