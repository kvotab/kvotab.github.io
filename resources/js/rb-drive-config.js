/* ==========================================================================
   GOOGLE DRIVE: THE GOOGLE CLOUD PROJECT

   The Google Drive button (rb-drive.js) signs in through the Google Cloud
   project named here. While any of the three is empty, the button is not
   shown and nothing of Google's is ever loaded.

     clientId  the OAuth client ID, of the type Web application, with
               https://kvotab.se among its authorised JavaScript origins
     apiKey    an API key restricted to the Google Picker API, and to the
               websites https://kvotab.se/* and https://docs.google.com/*
               (Google's picker runs in a frame from docs.google.com, and
               without that entry it reports the key as invalid)
     appId     the project NUMBER, not its ID: a string of digits, from the
               project's dashboard. The picker needs it so that the files
               picked are the ones this page may open.

   None of the three is a secret. They are in every copy of the page a
   browser loads, as Google intends for a page with no server: what keeps
   them from being used elsewhere is the restrictions set on them in the
   project.
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why
const RB_GOOGLE_DRIVE = Object.freeze({
  clientId: '653214542972-5o5p1d9ctu900d7arnfi1ji0deapffcb.apps.googleusercontent.com',
  apiKey: 'AIzaSyBWrH4zs18En-tQEL4dqCkpjmFQNnpDTu0',
  appId: '653214542972'
});
