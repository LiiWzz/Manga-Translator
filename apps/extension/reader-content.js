/* v0.4: read-only image discovery/locate. No mutation of image or DOM text. */
(() => {
 if (window.__mangaReaderInstalled) return;
 window.__mangaReaderInstalled = true;
 chrome.runtime.onMessage.addListener((message,_sender,sendResponse) => {
  if ((message.type === "MANGA_READER_DISCOVER" || message.type === "MANGA_READER_LOCATE")
      && message.pageUrl !== location.href) {
   sendResponse(false);
   return false;
  }
  if (message.type === "MANGA_READER_DISCOVER") {
   const results = [];
   [...document.images].forEach((img,index)=>{
    const rect=img.getBoundingClientRect();
    if(img.complete && img.naturalWidth>=350 && img.naturalHeight>=250 && rect.width>200
       && rect.bottom>0 && rect.top<innerHeight && (img.currentSrc||img.src)) {
      results.push({index,url:img.currentSrc||img.src});
    }
   });
   sendResponse(results.slice(0,3));
   return false;
  }
  if(message.type==="MANGA_READER_LOCATE"){
   // Lazy loading can insert images and invalidate the original document index.
   const img=[...document.images].find(image => (image.currentSrc||image.src)===message.url);
   if(img) img.scrollIntoView({behavior:"smooth",block:"center"});
   sendResponse(Boolean(img));
   return false;
  }
 });
})();
