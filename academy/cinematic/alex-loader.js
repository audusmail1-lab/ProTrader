// Public presentation settings reviewed against this agent on 13 October 2026.
// Conversation access, answers and agent policy still come from ElevenLabs.
export const ALEX_AGENT_ID='agent_4801m3by5dhceh5rwx83ynt33ra3';
const WIDGET_NAME='elevenlabs-convai';
const WIDGET_URL='/cinematic/elevenlabs-widget-0.18.3.js';
const SETTINGS_KEY='academy-alex-public-settings-v1';
const FRESH_MS=300000,RETRY_MS=30000,LOAD_MS=30000;
const BASE_SETTINGS={"variant":"full","placement":"bottom-right","expandable":"never","avatar":{"type":"orb","color_1":"#2792dc","color_2":"#9ce6e6"},"feedback_mode":"none","end_feedback":{"type":"rating"},"bg_color":"#ffffff","text_color":"#000000","btn_color":"#000000","btn_text_color":"#ffffff","border_color":"#e1e1e1","focus_color":"#000000","border_radius":null,"btn_radius":null,"action_text":null,"start_call_text":null,"end_call_text":null,"expand_text":null,"listening_text":null,"speaking_text":null,"shareable_page_text":null,"shareable_page_show_terms":true,"terms_text":null,"terms_html":null,"terms_key":null,"show_avatar_when_collapsed":false,"disable_banner":false,"override_link":null,"markdown_link_allowed_hosts":[],"markdown_link_include_www":true,"markdown_link_allow_http":true,"mic_muting_enabled":true,"transcript_enabled":true,"text_input_enabled":true,"conversation_mode_toggle_enabled":false,"default_expanded":false,"always_expanded":false,"dismissible":false,"show_agent_status":false,"show_conversation_id":true,"strip_audio_tags":true,"syntax_highlight_theme":null,"text_contents":{"main_label":null,"start_call":null,"start_chat":null,"new_call":null,"end_call":null,"mute_microphone":null,"change_language":null,"collapse":null,"expand":null,"copied":null,"accept_terms":null,"dismiss_terms":null,"listening_status":null,"speaking_status":null,"connecting_status":null,"chatting_status":null,"queue_waiting_status":null,"queue_waiting_status_short":null,"input_label":null,"input_placeholder":null,"input_placeholder_text_only":null,"input_placeholder_new_conversation":null,"user_ended_conversation":null,"agent_ended_conversation":null,"conversation_id":null,"error_occurred":null,"queue_timed_out":null,"copy_id":null,"initiate_feedback":null,"request_follow_up_feedback":null,"thanks_for_feedback":null,"thanks_for_feedback_details":null,"follow_up_feedback_placeholder":null,"submit":null,"go_back":null,"send_message":null,"text_mode":null,"voice_mode":null,"switched_to_text_mode":null,"switched_to_voice_mode":null,"copy":null,"download":null,"wrap":null,"agent_working":null,"agent_done":null,"agent_error":null,"attach_file":null,"remove_file":null,"file_upload_error":null,"file_type_unsupported":null,"file_too_large":null,"file_limit_reached":null,"typing_indicator":null,"rich_content_unavailable":null},"styles":{"base":null,"base_hover":null,"base_active":null,"base_border":null,"base_subtle":null,"base_primary":null,"base_error":null,"accent":null,"accent_hover":null,"accent_active":null,"accent_border":null,"accent_subtle":null,"accent_primary":null,"overlay_padding":null,"button_radius":null,"input_radius":null,"bubble_radius":null,"sheet_radius":null,"compact_sheet_radius":null,"dropdown_sheet_radius":null},"show_resize_button":true,"end_confirmation_enabled":false,"language":"en","supported_language_overrides":null,"language_presets":{},"text_only":false,"supports_text_only":true,"first_message":"[warmly] Hello there! I'm Alex, your customer support assistant for Pro Trader Academy. How can I help you learn more about our programs or assist you today?","use_rtc":null,"file_input_config":{"enabled":false,"max_files_in_memory":10,"max_files_per_conversation":10},"first_message_rich_content":null};
const isRecord=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const clone=value=>JSON.parse(JSON.stringify(value));
// Supported by the pinned widget; an unknown default crashes its locale provider.
const LANGUAGES=new Set('en zh es hi pt pt-br fr de ja ar ru ko id it nl tr pl sv ms ro uk el cs da fi bg hr sk ta hu no vi tl af hy as az be bn bs ca et gl ka gu ha he is ga jv kn kk ky lv lt lb mk ml mr ne ps fa pa sr sd sl so sw te th ur cy'.split(' '));

function validSettings(value){
  if(!isRecord(value)||!LANGUAGES.has(value.language)||!isRecord(value.avatar))return null;
  if(!['orb','image','url'].includes(value.avatar.type))return null;
  if(value.avatar.type==='orb'&&(!value.avatar.color_1||!value.avatar.color_2))return null;
  for(const key of ['styles','text_contents','language_presets','file_input_config'])
    if(value[key]!=null&&!isRecord(value[key]))return null;
  for(const key of ['terms_html','terms_text','terms_key'])
    if(value[key]!=null&&typeof value[key]!=='string')return null;
  if(value.supported_language_overrides!=null&&!Array.isArray(value.supported_language_overrides))return null;
  for(const [key,defaultValue] of Object.entries(BASE_SETTINGS))
    if(typeof defaultValue==='boolean'&&value[key]!=null&&typeof value[key]!=='boolean')return null;
  // Accept only public widget fields; never persist unrelated response data.
  return clone(Object.fromEntries(Object.keys(BASE_SETTINGS).filter(key=>Object.hasOwn(value,key)).map(key=>[key,value[key]])));
}
function adaptSettings(config){
  const copy=clone(config);
  return {...copy,first_message:'Hi, I’m Alex. What would you like to understand about the Academy or your workspace?',
    avatar:copy.avatar?.type==='orb'?{...copy.avatar,color_1:'#789166',color_2:'#d8e5bb'}:copy.avatar,
    styles:{...copy.styles,base:'#141d18',base_hover:'#243229',base_active:'#2d3d30',base_primary:'#edf1e9',base_subtle:'#aab9ad',base_border:'#344638',accent:'#cdddac',accent_hover:'#dae8c0',accent_active:'#bbcea0',accent_primary:'#182315',overlay_padding:0,button_radius:10,input_radius:10,sheet_radius:14}};
}

export function createAlexLoader({
  fetch:fetchSettings=(...args)=>globalThis.fetch(...args),
  storage=()=>globalThis.sessionStorage,
  document=()=>globalThis.document,
  registry=()=>globalThis.customElements,
  now=()=>Date.now(),
  setTimer=(fn,ms)=>setTimeout(fn,ms),
  clearTimer=id=>clearTimeout(id)
}={}){
  let settings=BASE_SETTINGS,loadedAt=-Infinity,attemptedAt=-Infinity,cacheRead=false,refresh=null;
  let widgetResource=null,widgetAttempt=null;
  function readCache(){
    if(cacheRead)return;cacheRead=true;
    try{
      const cached=JSON.parse(storage()?.getItem(SETTINGS_KEY)||'null');
      const config=cached?.agent===ALEX_AGENT_ID&&validSettings(cached.config);
      if(!config)return;
      // Keep known terms even when stale. Freshness controls refresh, not loss
      // of an already verified policy or a visitor's ability to open the UI.
      settings=config;
      if(Number.isFinite(cached.at)&&cached.at<=now())loadedAt=cached.at;
    }catch{/* Storage is optional, including in private browsing. */}
  }
  function refreshSettings(){
    if(refresh||now()-loadedAt<FRESH_MS||now()-attemptedAt<RETRY_MS)return;
    attemptedAt=now();
    const controller=new AbortController();let timer;
    const deadline=new Promise((_,reject)=>{timer=setTimer(()=>{controller.abort();reject(new Error('Settings refresh timed out'))},LOAD_MS)});
    const request=Promise.resolve().then(()=>fetchSettings(`https://api.elevenlabs.io/v1/convai/agents/${ALEX_AGENT_ID}/widget`,{signal:controller.signal}))
      .then(response=>{if(!response.ok)throw new Error('Settings unavailable');return response.json()})
      .then(response=>{
        if(response.agent_id!==ALEX_AGENT_ID)throw new Error('Unexpected agent settings');
        const config=validSettings(response.widget_config);
        if(!config)throw new Error('Invalid widget settings');
        return config;
      });
    refresh=Promise.race([request,deadline]).then(config=>{
      settings=config;loadedAt=now();
      try{storage()?.setItem(SETTINGS_KEY,JSON.stringify({agent:ALEX_AGENT_ID,at:loadedAt,config}))}catch{/* Optional cache. */}
    }).catch(()=>{/* Existing presentation settings remain usable. */}).finally(()=>{clearTimer(timer);refresh=null});
  }
  function getAlexSettings(){
    readCache();refreshSettings();
    // Each mount receives its own snapshot. Background refresh never changes
    // a mounted conversation, its consent state, or its transcript.
    return adaptSettings(settings);
  }
  function startWidget(){
    let resolve,reject,script,retries=0,settled=false;
    const resource={promise:new Promise((yes,no)=>{resolve=yes;reject=no})};
    const finish=error=>{
      if(settled)return;settled=true;
      if(script){script.onload=null;script.onerror=null}
      if(error){script?.remove();if(widgetResource===resource)widgetResource=null;reject(error)}else resolve();
    };
    const append=()=>{
      try{
        script=document().createElement('script');script.src=WIDGET_URL;script.async=true;
        script.onerror=()=>{
          script.onload=null;script.onerror=null;script.remove();
          // A definite network failure can safely retry. A timeout cannot:
          // the original script may still evaluate, so keep observing it.
          if(retries++===0)append();else finish(new Error('Alex could not load.'));
        };
        script.onload=()=>finish(registry().get(WIDGET_NAME)?undefined:new Error('Alex did not initialize.'));
        document().head.append(script);
      }catch(error){finish(error)}
    };
    try{registry().whenDefined(WIDGET_NAME).then(()=>finish(),finish)}catch(error){finish(error)}
    if(!settled)append();
    return resource;
  }
  function loadAlexWidget(){
    try{if(registry().get(WIDGET_NAME))return Promise.resolve()}catch(error){return Promise.reject(error)}
    if(widgetAttempt)return widgetAttempt;
    if(!widgetResource)widgetResource=startWidget();
    const resource=widgetResource;let timer;
    const deadline=new Promise((_,reject)=>{timer=setTimer(()=>reject(new Error('Alex could not load.')),LOAD_MS)});
    widgetAttempt=Promise.race([resource.promise,deadline]).finally(()=>{
      clearTimer(timer);widgetAttempt=null;
    });
    // Synchronous document failures settle before resource assignment.
    resource.promise.catch(()=>{if(widgetResource===resource)widgetResource=null});
    return widgetAttempt;
  }
  return {getAlexSettings,loadAlexWidget};
}
const loader=createAlexLoader();
export const getAlexSettings=()=>loader.getAlexSettings();
export const loadAlexWidget=()=>loader.loadAlexWidget();
