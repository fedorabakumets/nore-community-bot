'use strict';
window.NoraShop=(()=>{
  let category=null,sequence=0;
  const paths={pets:'M8 11c-2 0-4 3-4 5s2 3 4 2c2-1 2-1 4-1s2 0 4 1c2 1 4 0 4-2s-2-5-4-5c-2 0-2 1-4 1s-2-1-4-1z M5 5v2 M10 3v3 M15 3v3 M20 5v2',reputation:'M12 2 21 6v6c0 5-9 10-9 10S3 17 3 12V6z M8 11l3 3 5-6',profile:'M5 21v-2a7 7 0 0 1 14 0v2 M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8',cookies:'M21 12a9 9 0 1 1-9-9c-1 3 0 5 3 5 0 3 2 4 6 4z M7 8h.1 M8 15h.1 M14 16h.1',other:'M4 8h16v13H4z M8 8V5a4 4 0 0 1 8 0v3'};
  function arrow(){return '<svg class="shop-arrow" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 13 13 3M4 3h9v9" fill="none" stroke="currentColor" stroke-width="1.7"/></svg>'}
  function quantity(n){return number(n)+' '+(n%100>=11&&n%100<=14?NoraI18n.t("товаров"):n%10===1?NoraI18n.t("товар"):n%10>=2&&n%10<=4?NoraI18n.t("товара"):NoraI18n.t("товаров"))}
  function catSub(c,n){const d=String(c.description||'').replace(/[\s.,;:·—–-]+$/u,'').trim();return d?`${esc(d)} · ${quantity(n)}`:`${quantity(n)}`}
  function svg(id){return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[id]||paths.other}"/></svg>`}
  function title(text){return String(text||'').replace(/^[\p{Extended_Pictographic}\p{Emoji_Presentation}\uFE0F\u200D\s]+/u,'').trim()}
  function repMeta(){const tier=String(data.profile.tier||'').toLowerCase();const metal=tier.includes('золот')?'gold':tier.includes('сереб')?'silver':'bronze';return {metal,medal:metal==='gold'?'🥇':metal==='silver'?'🥈':'🥉',label:NoraI18n.t(data.profile.tier)||NoraI18n.t("бронза"),discount:Number(data.profile.discount||0),value:Number(data.user.reputation||0)}}
  function repButton(){const m=repMeta();return `<button class="shop-rep shop-rep-${m.metal}" data-reputation aria-label="${NoraI18n.html("Репутация:")} ${esc(m.label)} ${NoraI18n.html("· скидка")} ${number(m.discount)}%"><span class="shop-rep-medal" aria-hidden="true">${m.medal}</span><span class="shop-rep-copy"><small>${NoraI18n.html("Репутация ·")} ${number(m.value)} / 100</small><b>${esc(m.label.replace(/^./,c=>c.toUpperCase()))} ${NoraI18n.html("· скидка")} ${number(m.discount)}%</b></span><span class="shop-rep-arrow" aria-hidden="true">${arrow()}</span></button>`}
  function price(p,gift=false){if(p.mode==='amount')return NoraI18n.t("На твой выбор");if(p.mode==='event'&&p.price===0)return NoraI18n.t("Бесплатно");if(!p.price)return NoraI18n.t("Пока недоступно");const tier=String(data.profile.tier||'').toLowerCase(),metal=tier.includes('золот')?'gold':tier.includes('сереб')?'silver':'bronze',value=gift?Math.floor((Number(p.base_price)*110+99)/100):p.price;return `<span class="shop-price-pair">${!gift&&p.base_price>p.price?`<del>${number(p.base_price)} 🍪</del>`:''}<strong class="metal-price ${gift?'gift-price':metal}">${number(value)} <svg class="metal-cookie ${gift?'gold':metal}" viewBox="0 0 32 32" role="img" aria-label="${NoraI18n.html("печеньки")}"><path fill="currentColor" d="M23 3a6 6 0 0 0 6 8c5 13-5 22-16 18C1 26-1 11 8 5c5-4 10-4 15-2Z"/><g fill="#30231e"><circle cx="11" cy="10" r="2"/><circle cx="9" cy="21" r="2"/><circle cx="20" cy="22" r="2.5"/><circle cx="17" cy="15" r="1.7"/></g></svg></strong>${gift?("<small>" + NoraI18n.html("+10% за подарок · без скидки уровня") + "</small>"):''}</span>`}

  function cards(list){return list.length?`<div class="grid shop-products">${list.map(p=>`<button class="product ${p.buyable?'':'product-unavailable'}" data-product="${esc(p.sku)}"><span class="icon">${svg(p.category)}</span><h3>${esc(title(NoraI18n.t(p.title)))}</h3><span class="product-summary">${esc(p.description||'')}</span><span class="cost">${price(p)}</span><span class="plus" aria-hidden="true">${arrow()}</span></button>`).join('')}</div>`:("<div class=\"card empty\">" + NoraI18n.html("На этой полке пока пусто.") + "<br>" + NoraI18n.html("Скоро здесь появится что-нибудь приятное.") + "</div>")}
  function featured(){const f=data.featured,p=f&&data.products.find(p=>p.sku===f.sku);if(!p)return '';return `<button class="category-card shop-featured" data-product="${esc(p.sku)}"><span class="category-symbol">${svg(p.category)}</span><span><small class="eyebrow">${NoraI18n.html("На витрине")}${f.stock?NoraI18n.t(" · осталось ")+esc(f.stock):''}</small><b>${esc(title(f.title||NoraI18n.t(p.title)))}</b><small>${price(p)}${f.until?NoraI18n.t(" · до ")+esc(new Date(f.until).toLocaleString(NoraI18n.locale)):''}</small></span><span class="category-arrow">${arrow()}</span></button>`}
  function screen(){const u=data.user;if(category==='__cookies'&&!data.cookie_shop?.enabled)category=null;const c=data.categories.find(c=>c.id===category);if(category&&category!=='__cookies'&&!c)category=null;const intro=`<div class="shop-balance"><span>${NoraI18n.html("Твой баланс")} <b>${number(u.cookies)} 🍪</b></span></div>`;if(category==='__cookies')return `<button class="text-btn shop-back" data-shop-root>${NoraI18n.html("← Все категории")}</button><p class="eyebrow">${NoraI18n.html("В общий кошелёк")}</p><h1>${NoraI18n.html("Больше")}<br><em>${NoraI18n.html("печенек")}</em></h1>${intro}<p class="sub">${esc(NoraI18n.t(data.cookie_shop.intro))}<br>1 🍪 = ${number(data.cookie_shop.rate_rub)} ${NoraI18n.html("₽. Пакеты без скидки репутации.")}</p><div class="cookie-packs">${data.cookie_shop.packs.map(n=>`<button class="category-card" data-topup="${n}"><span class="category-symbol">${svg('cookies')}</span><span><b>${number(n)} 🍪</b><small>${number(n*data.cookie_shop.rate_rub)} ₽</small></span><span class="category-arrow">${arrow()}</span></button>`).join('')}</div><p class="footer-note">${NoraI18n.html("Оплата через СБП. Квитанцию можно отправить здесь.")}<br>${NoraI18n.html("Начисление — после проверки администратором.")}</p>`;
    if(category&&c)return `<button class="text-btn shop-back" data-shop-root>${NoraI18n.html("← Все категории")}</button><p class="eyebrow">${NoraI18n.html("Магазин Норы")}</p><h1>${esc(title(NoraI18n.t(c.title)))}</h1>${intro}<p class="sub shop-intro">${esc(NoraI18n.t(c.description))}</p>${category==='pets'&&data.pet?`<section class="card shop-pet"><b>${esc(data.pet.name)}</b><p>${NoraI18n.html("Сытость")} ${number(data.pet.hunger)} ${NoraI18n.html("/ 100 · Вода")} ${number(data.pet.thirst)} / 100</p></section>`:''}${cards(data.products.filter(p=>p.category===category))}<p class="footer-note">${NoraI18n.html("Та же полка и цены, что в боте.")}<br>${NoraI18n.html("Списание — только после подтверждения.")}</p>`;
    return `<div class="shop-root-heading nora-page-heading"><h1>${NoraI18n.html("Магазин")}</h1>${intro}</div>${repButton()}${data.header?.enabled?`<section class="card shop-header"><h2>${esc(data.header.title)}</h2><p class="sub">${esc(data.header.text)}</p></section>`:''}${featured()}<section class="shop-shelf" aria-labelledby="shop-shelf-title"><h2 id="shop-shelf-title">${NoraI18n.html("Категории")}</h2><div class="shop-categories">${data.categories.map(c=>`<button class="category-card" data-shop-category="${esc(c.id)}"><span class="category-symbol">${svg(c.id)}</span><span><b>${esc(title(NoraI18n.t(c.title)))}</b><small>${catSub(c,data.products.filter(p=>p.category===c.id).length)}</small></span><span class="category-arrow">${arrow()}</span></button>`).join('')}${data.cookie_shop?.enabled?`<button class="category-card" data-shop-category="__cookies"><span class="category-symbol">${svg('cookies')}</span><span><b>${NoraI18n.html("Купить печеньки")}</b><small>${NoraI18n.html("Пакеты через СБП · в общий кошелёк")}</small></span><span class="category-arrow">${arrow()}</span></button>`:''}</div></section>${seasonalCards()}`}

  let seasonalPending=false;
  const seasonalPreloads=new Map();
  function preloadSeasonal(){for(const item of data.seasonal_items||[]){if(!item.image||seasonalPreloads.has(item.image))continue;const img=new Image();seasonalPreloads.set(item.image,img);img.onerror=()=>seasonalPreloads.delete(item.image);img.src=item.image}}
  function seasonalCards(){
    const list=data.seasonal_items||[data.seasonal].filter(Boolean);
    const canManage=data.can_manage_seasonal??list[0]?.can_manage;
    return `${canManage?("<button class=\"secondary\" data-seasonal-new>" + NoraI18n.html("＋ Новый сезонный предмет") + "</button>"):''}${list.map(seasonalCard).join('')}`;
  }
  function seasonalCard(s){
    const sale=s.mode==='paid', paidEntry=s.mode==='paid_raffle', closed=s.status!=='open', id=esc(s.id);
    const price=sale||paidEntry?number(s.price)+' 🍪':NoraI18n.t("Бесплатно");
    const action=s.enabled===false?NoraI18n.t("Скрыт"):closed?NoraI18n.t("Завершено"):s.joined
      ?(sale?NoraI18n.t("Вы купили ✓"):NoraI18n.t("Вы участвуете ✓"))
      :(sale?NoraI18n.t("Купить"):paidEntry?NoraI18n.t("Оплатить участие"):NoraI18n.t("Участвовать"));
    return `<article class="seasonal-drop">
      <img class="seasonal-cover" src="${esc(s.image)}" alt="" loading="lazy">
      <div class="seasonal-copy">
        <div class="seasonal-badges"><span>${NoraI18n.html("Сезон 1 · Bloody Nora")}</span><span>${sale?NoraI18n.t("Товар"):paidEntry?NoraI18n.t("Платный розыгрыш"):NoraI18n.t("Розыгрыш")}</span>${s.enabled===false?("<span>" + NoraI18n.html("Скрыт") + "</span>"):''}</div>
        <h2>${esc(NoraI18n.t(s.title))}</h2>
        <p class="seasonal-intro">${esc(s.description)}</p>
        <div class="seasonal-meta"><span>${sale?NoraI18n.t("Цена"):NoraI18n.t("Участие")} <b>${price}</b></span><span>${sale?NoraI18n.t("Покупателей"):NoraI18n.t("Участников")} <b>${number(s.count)}</b></span></div>
        ${!sale&&closed?`<p class="seasonal-result">${s.won?NoraI18n.t("Вы победили!"):`${NoraI18n.t("Победитель:")} ${esc(s.winner||NoraI18n.t("итог сохранён"))}`}</p>`:''}
        <button class="primary seasonal-join" data-seasonal-action="${id}" ${closed||s.joined||s.enabled===false?'disabled':''}>${action}</button>
        <p class="footer-note">${sale?NoraI18n.t("После покупки администрация свяжется с вами."):NoraI18n.t("Одна заявка на человека.")}</p>
        <details class="seasonal-details">
          <summary>${NoraI18n.html("Подробнее")}</summary>
          <div class="seasonal-author"><b><a href="${esc(s.author_url)}" target="_blank" rel="noopener noreferrer">${esc(s.author)} ↗</a></b>
            <div class="seasonal-links">${(s.links||[]).map(l=>`<a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.label)} ↗</a>`).join('')}</div>
          </div>
        </details>
        ${s.can_manage?`<button class="text-btn seasonal-admin" data-seasonal-edit="${id}">${NoraI18n.html("Редактировать предмет")}</button>
          <button class="text-btn seasonal-admin" data-seasonal-manage="${id}" data-offset="0">${sale?NoraI18n.t("Покупатели"):NoraI18n.t("Участники и итоги")}</button>`:''}
      </div>
    </article>`;
  }
  function seasonalEdit(id,source){
    if(seasonalPending)return;
    const existing=data.seasonal_items?.find(x=>x.id===id);
    const s=existing||source||{title:'',description:'',image:'',author:'',author_url:'',links:[],mode:'raffle',price:0};
    const mode=source?'paid':s.mode||'raffle';
    const locked=existing&&(existing.count>0||existing.status!=='open');
    const links=(s.links||[]).map(l=>l.label+' | '+l.url).join('\n');
    sheet(`<span class="eyebrow">${NoraI18n.html("Сезонный предмет")}</span><h2>${id?NoraI18n.t("Редактировать"):source?NoraI18n.t("Новый товар"):NoraI18n.t("Новый предмет")}</h2>
      <form id="seasonal-edit-form">
        <label>${NoraI18n.html("Название")}<input name="title" maxlength="100" required value="${esc(NoraI18n.t(s.title))}"></label>
        <label>${NoraI18n.html("Описание")}<textarea name="description" maxlength="1500" required>${esc(s.description)}</textarea></label>
        <label>${NoraI18n.html("Изображение")}<input name="image_file" type="file" accept="image/jpeg,image/png,image/webp" ${s.image?'':'required'}></label>
        <p class="sub">${NoraI18n.html("JPG, PNG или WebP до 5 МБ.")}${s.image?NoraI18n.t(" Текущее изображение сохранится, если не выбрать новый файл."):''}</p>
        <label>${NoraI18n.html("Автор")}<input name="author" maxlength="100" required value="${esc(s.author)}"></label>
        <label>${NoraI18n.html("Ссылка на автора")}<input name="author_url" type="url" maxlength="2048" required value="${esc(s.author_url)}"></label>
        <label>${NoraI18n.html("Источники (название | HTTPS-ссылка, по одному на строку)")}<textarea name="links" rows="6">${esc(links)}</textarea></label>
        <label class="shop-gift-check"><input name="enabled" type="checkbox" ${source||s.enabled!==false?'checked':''}> ${NoraI18n.html("Показывать в магазине")}</label>
        <label>${NoraI18n.html("Способ получения")}<select name="mode" ${locked?'disabled':''}>
          <option value="raffle" ${mode==='raffle'?'selected':''}>${NoraI18n.html("Бесплатный розыгрыш")}</option>
          <option value="paid_raffle" ${mode==='paid_raffle'?'selected':''}>${NoraI18n.html("Платное участие в розыгрыше")}</option>
          <option value="paid" ${mode==='paid'?'selected':''}>${NoraI18n.html("Продажа товара за печеньки")}</option>
        </select></label>
        ${locked?("<p class=\"sub\">" + NoraI18n.html("После первой заявки или покупки способ получения закреплён за карточкой.") + "</p>"):''}
        <label id="seasonal-price-field">${NoraI18n.html("Цена в печеньках")}<input name="price" type="number" inputmode="numeric" min="1" max="1000000" value="${source?'':Number(s.price||0)||''}"></label>
        <button class="primary" type="submit">${NoraI18n.html("Сохранить")}</button>
        ${locked&&mode!=='paid'?("<button class=\"secondary\" type=\"button\" id=\"seasonal-copy-as-sale\">" + NoraI18n.html("Создать товар из этой карточки") + "</button>"):''}
        ${id?("<button class=\"text-btn danger-action\" type=\"button\" id=\"seasonal-remove\">" + NoraI18n.html("Удалить предмет") + "</button>"):''}
      </form>`);
    const form=$('#seasonal-edit-form');
    const modeSelect=form.elements.mode;
    const priceInput=form.elements.price;
    function syncPrice(){
      const free=modeSelect.value==='raffle';
      $('#seasonal-price-field').hidden=free;
      priceInput.disabled=free;
      priceInput.required=!free;
    }
    syncPrice();
    modeSelect.onchange=syncPrice;
    if($('#seasonal-copy-as-sale'))$('#seasonal-copy-as-sale').onclick=()=>seasonalEdit(null,s);
    if(id)$('#seasonal-remove').onclick=()=>seasonalRemove(s);
    form.onsubmit=async e=>{
      e.preventDefault();
      if(seasonalPending)return;
      const fields=new FormData(form);
      const lines=String(fields.get('links')).split('\n').map(x=>x.trim()).filter(Boolean);
      const links=[];
      for(const line of lines){
        const i=line.indexOf('|');
        if(i<0){toast(NoraI18n.t("Укажите название и ссылку через |"));return}
        links.push({label:line.slice(0,i).trim(),url:line.slice(i+1).trim()});
      }
      const file=fields.get('image_file');
      if(file?.size>5*1024*1024){toast(NoraI18n.t("Фото должно быть не больше 5 МБ"));return}
      const item={
        title:fields.get('title'),description:fields.get('description'),image:s.image,
        author:fields.get('author'),author_url:fields.get('author_url'),links,
        mode:modeSelect.value,price:Number(fields.get('price')),enabled:fields.has('enabled'),
      };
      seasonalPending=true;
      try{
        if(file?.size)item.image=(await upload('seasonal/upload',null,file)).image;
        const r=await api('seasonal/save',{id,item});
        updateSeasonalItems(r.items);
        $('#sheet').close();
        render();
        toast(NoraI18n.t("Предмет сохранён"));
      }catch(err){toast(err.message)}finally{seasonalPending=false}
    };
  }
  function updateSeasonalItems(items){
    data.seasonal_items=items;
    data.seasonal=items.find(item=>item.id==='season1-crimson-guardian');
  }
  function seasonalRemove(s){
    if(seasonalPending)return;
    const details=s.mode==='paid'?NoraI18n.t("Продажи закроются. История покупок сохранится.")
      :s.status==='open'?NoraI18n.t("Розыгрыш закроется без выбора победителя. Заявки сохранятся.")
      :NoraI18n.t("Карточка исчезнет из магазина. Итоги сохранятся.");
    const paidEntries=s.mode==='paid_raffle'&&s.status==='open';
    sheet(`<h2>${NoraI18n.html("Удалить «")}${esc(NoraI18n.t(s.title))}»?</h2><p>${details}${paidEntries?NoraI18n.t(" Возврат печенек оформляется отдельно."):''}</p>
      <button class="primary" type="button" id="seasonal-remove-confirm">${NoraI18n.html("Удалить предмет")}</button>`);
    $('#seasonal-remove-confirm').onclick=async()=>{
      if(seasonalPending)return;
      seasonalPending=true;
      try{
        const r=await api('seasonal/remove',{id:s.id});
        updateSeasonalItems(r.items);
        $('#sheet').close();
        render();
        toast(NoraI18n.t("Предмет удалён"));
      }catch(err){toast(err.message)}finally{seasonalPending=false}
    };
  }
  async function seasonalAction(id){
    if(seasonalPending||busy)return;
    const s=data.seasonal_items?.find(x=>x.id===id);
    if(!s)return;
    seasonalPending=true;
    try{
      if(s.mode!=='paid'&&s.mode!=='paid_raffle'){
        const r=await api('seasonal/join',{id});
        updateSeasonalItems((await api('seasonal/items')).items);
        render();
        toast(r.message);
        return;
      }
      const q=await api('seasonal/buy/prepare',{id});
      const entry=q.mode==='paid_raffle';
      sheet(`<span class="eyebrow">${entry?NoraI18n.t("Платное участие"):NoraI18n.t("Подтверждение покупки")}</span><h2>${esc(q.title)}</h2>
        <p>${NoraI18n.html("Стоимость")} ${entry?NoraI18n.t("заявки"):NoraI18n.t("товара")} <b>${number(q.price)} 🍪</b>. ${entry?NoraI18n.t("Оплата даёт один шанс в розыгрыше."):NoraI18n.t("После покупки администрация свяжется с вами.")}</p>
        <button class="primary" id="seasonal-buy-confirm">${entry?NoraI18n.t("Оплатить заявку"):NoraI18n.t("Подтвердить покупку")}</button>`);
      $('#seasonal-buy-confirm').onclick=async()=>{
        if(seasonalPending)return;
        seasonalPending=true;
        try{
          const r=await api('seasonal/buy/confirm',{token:q.token});
          updateSeasonalItems(r.items);
          $('#sheet').close();
          await refresh();
          toast(r.message);
        }catch(err){toast(err.message)}finally{seasonalPending=false}
      };
    }catch(err){toast(err.message)}finally{seasonalPending=false}
  }
  async function seasonalManage(id,offset=0){if(seasonalPending)return;seasonalPending=true;try{const r=await api('seasonal/manage?id='+encodeURIComponent(id)+'&offset='+offset),paid=r.seasonal.mode==='paid';sheet(`<span class="eyebrow">${paid?NoraI18n.t("Покупатели"):NoraI18n.t("Участники розыгрыша")}</span><h2>${esc(r.seasonal.title)}</h2><p>${NoraI18n.html("Всего:")} <b>${number(r.seasonal.count)}</b></p>${r.seasonal.winner?`<p>${NoraI18n.html("Победитель:")} <b>${esc(r.seasonal.winner)}</b></p>`:''}<div class="seasonal-roster">${r.items.map(p=>`<p><b>${esc(p.profile_name||p.telegram_name)}</b><small>${p.username?'@'+esc(p.username):'ID '+number(p.user_id)} · ${esc(new Date(p.joined_at).toLocaleString(NoraI18n.locale))}</small></p>`).join('')||("<p class=\"sub\">" + NoraI18n.html("Список пуст.") + "</p>")}</div><div class="pet-action-row">${offset?`<button class="secondary" data-seasonal-manage="${esc(id)}" data-offset="${Math.max(0,offset-20)}">${NoraI18n.html("← Назад")}</button>`:''}${r.has_more?`<button class="secondary" data-seasonal-manage="${esc(id)}" data-offset="${offset+20}">${NoraI18n.html("Далее →")}</button>`:''}</div>${!paid&&r.seasonal.status==='open'?`<button class="primary" id="seasonal-prepare-draw" ${!r.seasonal.count?'disabled':''}>${NoraI18n.html("Подвести итоги…")}</button>`:''}`);const b=document.querySelector('#seasonal-prepare-draw');if(b)b.onclick=()=>seasonalPrepare(id)}catch(e){toast(e.message)}finally{seasonalPending=false}}
  async function seasonalPrepare(id){if(seasonalPending)return;seasonalPending=true;try{const q=await api('seasonal/draw/prepare',{id});sheet(`<span class="eyebrow">${NoraI18n.html("Подтверждение итогов")}</span><h2>${esc(q.title)}</h2><p class="sub">${NoraI18n.html("Среди")} ${number(q.count)} ${NoraI18n.html("участников сервер случайно выберет победителя. Повторный выбор невозможен.")}</p><button class="primary" id="seasonal-confirm-draw">${NoraI18n.html("Завершить и выбрать победителя")}</button>`);document.querySelector('#seasonal-confirm-draw').onclick=async()=>{if(seasonalPending)return;seasonalPending=true;try{const result=await api('seasonal/draw/confirm',{token:q.token,id});updateSeasonalItems((await api('seasonal/items')).items);document.querySelector('#sheet').close();render();toast(result.message)}catch(e){toast(e.message)}finally{seasonalPending=false}}}catch(e){toast(e.message)}finally{seasonalPending=false}}
  document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.hasAttribute('data-seasonal-new'))seasonalEdit(null);if(b.hasAttribute('data-seasonal-edit'))seasonalEdit(b.dataset.seasonalEdit);if(b.hasAttribute('data-seasonal-action'))seasonalAction(b.dataset.seasonalAction);if(b.hasAttribute('data-seasonal-manage'))seasonalManage(b.dataset.seasonalManage,Number(b.dataset.offset||0))});

  function route(){const u=new URL(location.href),view=u.searchParams.get('view');if(view)return {view,category:u.searchParams.get('category')};try{if(location.hash.startsWith('#shop/'))return {view:'shop',category:decodeURIComponent(location.hash.slice(6))};const legacy=location.hash.match(/^#(home|shop|pet|lk|wallet|history|notices|admin|interactive|games|friends|community|events|mafia|rocket|sea|durak|barricade)(?:[&?]|$)/);return {view:legacy?.[1]||'home',category:null}}catch{return {view:'home',category:null}}}
  let backPending=false, afterGameBack, closingGuard=false;
  function writeRoute(next,push=false,petFrom=null){const u=new URL(location.href);u.searchParams.set('view',next);if(next==='shop'&&category)u.searchParams.set('category',category);else u.searchParams.delete('category');if(/^#(?:home|shop|pet|lk|wallet|history|notices|admin|interactive|games|friends|community|events|mafia|rocket|sea|durak|barricade)(?:\/[^&?]*)?$/.test(u.hash))u.hash='';history[push?'pushState':'replaceState']({noraView:next,petFrom},'',u)}
  function navigate(next,push=true){
    leaveGameTo('shop',()=>{
      category=next;tab='shop';writeRoute(tab,push);render();window.scrollTo(0,0);syncBack();
    });
  }
  function parent(){return tab==='pet'?(history.state?.petFrom||'community'):
    (['durak','barricade','dot','poker'].includes(tab)&&'games')||(tab==='commands'&&'home')||window.NoraInteractive?.parent(tab)||(tab==='sea'&&window.NoraSea?.parent?.())||window.NoraCabinet?.parent(tab)}
  function confirmUnload(event){event.preventDefault();event.returnValue=true}
  function pushGameGuard(game){
    if(game==='world')history.pushState(history.state,'',location.href);
    else writeRoute(tab,true);
    history.replaceState({...history.state,noraGameExit:true},'',location.href);
  }
  const profileDialog=$('#sheet');
  const nativeProfileBack=Boolean(tg?.isVersionAtLeast?.('6.1')&&
    typeof tg.BackButton?.show==='function'&&typeof tg.BackButton?.onClick==='function');
  function profileOpen(){return profileDialog.open&&Boolean(profileDialog.querySelector('#person-profile, #music-library-profile, #nora-now-playing'))}
  function syncBack(){
    const profileBack=nativeProfileBack&&profileOpen();
    profileDialog.classList.toggle('native-profile-back',profileBack);
    const game=currentGame();
    if(game&&!history.state?.noraGameExit&&!afterGameBack){
      // Preserve a same-document Back destination, including for direct game links.
      if(game!=='world'&&route().view===tab)writeRoute('games');
      pushGameGuard(game);
    }
    if(Boolean(game)!==closingGuard){
      closingGuard=Boolean(game);
      if(closingGuard){
        tg?.enableClosingConfirmation?.();
        window.addEventListener('beforeunload',confirmUnload);
      }else{
        tg?.disableClosingConfirmation?.();
        window.removeEventListener('beforeunload',confirmUnload);
      }
    }
    if(profileBack||game||category&&tab==='shop'||parent())tg?.BackButton?.show();else tg?.BackButton?.hide();
  }
  function exitGameView(onExit){
    requestGameExit(()=>{
      if(!history.state?.noraGameExit){onExit();return}
      afterGameBack=onExit;
      history.back();
    });
  }
  function leaveGameTo(next,onExit){
    const game=currentGame();
    if(game==='world')exitGameView(()=>{
      window.NoraGame.close();
      onExit();
    });
    else if(game&&next!==tab)exitGameView(onExit);
    else onExit();
  }
  function resume(initialCategory=route().category){category=initialCategory;syncBack()}
  function tabChanged(next,previous){
    if(gameViews.has(next)){syncBack();return}
    if(next==='pet'){
      if(previous&&previous!=='pet'){
        // Keep the actual parent in browser history for the WebView edge gesture.
        writeRoute(previous);
        writeRoute(next,true,previous);
      }else if(history.state?.noraView!=='pet')writeRoute(next);
    }else writeRoute(next);
    syncBack();
  }
  function renderQuote(q){sheet(`<span class="eyebrow">${NoraI18n.html("Проверим покупку")}</span><h2>${esc(title(q.title))}</h2><p class="sub">${esc(q.description)}${q.recipient?`<br><br>${NoraI18n.html("Подарок для")} <b>${esc(q.recipient)}</b>`:''}</p><div class="amount">${number(q.price)} 🍪</div><p class="sub">${NoraI18n.html("Баланс сейчас:")} ${number(data.user.cookies)} 🍪.<br>${q.gift?NoraI18n.t("Подарок: +10% к базовой цене, скидка уровня не применяется."):NoraI18n.t("Цена учитывает твою скидку.")}</p><button class="primary" id="pay" ${Number(data.user.cookies)<q.price?'disabled':''}>${Number(data.user.cookies)<q.price?NoraI18n.t("Недостаточно печенек"):NoraI18n.t("Подтвердить покупку")}</button>`);$('#pay').onclick=()=>perform('shop/confirm',{token:q.token})}
  async function product(sku){if(busy){toast(NoraI18n.t("Секунду, обновляем магазин"));return}const p=data.products.find(p=>p.sku===sku);if(!p)return;if(data.profile.fill_percent<100){toast(NoraI18n.t("Заполни профиль на 100% в ЛК"));return}const seq=++sequence;if(p.mode==='event'){const e=data.events[0];if(!e){toast(NoraI18n.t("Сейчас нет опубликованного мероприятия"));return}sheet(`<span class="eyebrow">${NoraI18n.html("Встретимся?")}</span><h2>${esc(e.title)}</h2><div class="amount">${e.price?number(e.price)+' 🍪':NoraI18n.t("Бесплатно")}</div><button class="primary" id="pay" ${e.paid||!e.price&&e.joined?'disabled':''}>${e.paid||!e.price&&e.joined?NoraI18n.t("Ты в списке участников"):NoraI18n.t("Подтвердить участие")}</button>`);$('#pay').onclick=()=>perform('events/join',{event_id:e.id,price:e.price});return}
    sheet(`<span class="eyebrow">${esc(title(data.categories.find(c=>c.id===p.category)?.title||NoraI18n.t("Магазин")))}</span><h2>${esc(title(NoraI18n.t(p.title)))}</h2>${p.image?`<div class="shop-product-image" data-shop-image="${esc(p.sku)}"></div>`:''}<p class="sub">${esc(NoraI18n.t(p.description))}</p><div class="amount" id="shop-product-price">${price(p)}</div>${p.reason?`<p class="shop-unavailable">${esc(NoraI18n.t(p.reason))}</p>`:''}<form id="shop-product-form">${p.mode==='pet'?`<label>${NoraI18n.html("Твой питомец")}<select name="species">${data.species.map(s=>`<option value="${esc(s.id)}">${esc(s.emoji+' '+NoraI18n.t(s.title))}</option>`).join('')}</select></label><label>${NoraI18n.html("Имя")}<input name="name" maxlength="24" required placeholder="${NoraI18n.html("Как его зовут?")}"></label>`:''}${p.mode==='video'?("<label>" + NoraI18n.html("Видео MP4") + "<input name=\"video\" type=\"file\" accept=\"video/mp4\" required></label><p class=\"sub\">" + NoraI18n.html("До 20 МБ. Загрузим в Telegram, затем отдельно подтвердим покупку.") + "</p>"):''}${p.mode==='amount'?("<label>" + NoraI18n.html("Сумма в печеньках") + "<input name=\"amount\" type=\"number\" inputmode=\"numeric\" min=\"1\" max=\"1000000\" required></label>"):''}${p.giftable?("<label class=\"shop-gift-check\"><input type=\"checkbox\" id=\"shop-gift\"> " + NoraI18n.html("Подарить участнику") + "</label><label id=\"recipient-label\" hidden>" + NoraI18n.html("Получатель") + "<input name=\"recipient\" maxlength=\"40\" placeholder=\"" + NoraI18n.html("@username или Telegram ID") + "\" disabled></label>"):''}<button class="primary" type="submit" id="shop-next" ${p.buyable?'':'disabled'}>${NoraI18n.html("Перейти к подтверждению")}</button></form>`);
    if(p.image)loadImage(p.sku,seq);if(p.giftable)$('#shop-gift').onchange=e=>{const input=$('[name="recipient"]');$('#recipient-label').hidden=!e.target.checked;input.disabled=!e.target.checked;input.required=e.target.checked;$('#shop-product-price').innerHTML=price(p,e.target.checked)};
    $('#shop-product-form').onsubmit=async e=>{e.preventDefault();if(busy)return;const form=e.target,body={sku};for(const [k,v] of new FormData(form))if(k!=='video')body[k]=k==='amount'?Number(v):v;const file=form.querySelector('[name="video"]')?.files?.[0];if(file&&(file.size>20*1024*1024||file.type!=='video/mp4')){toast(NoraI18n.t("Выбери видео MP4 до 20 МБ"));return}busy=true;$('#shop-next').disabled=true;$('#shop-next').textContent=NoraI18n.t("Проверяем…");try{const q=await api('shop/prepare',body);if(file)await upload('shop/video',q.token,file);if(seq===sequence&&$('#sheet').open)renderQuote(q)}catch(err){toast(err.message);if($('#shop-next')){$('#shop-next').disabled=false;$('#shop-next').textContent=NoraI18n.t("Повторить")}}finally{busy=false}}}
  async function upload(path,token,file){const r=await fetch('/api/'+path,{method:'POST',headers:{Authorization:'tma '+auth,'Content-Type':file.type||'application/octet-stream',...(token?{'X-Shop-Token':token}:{})},body:file});const j=await r.json();if(!r.ok)throw Error(j.error||NoraI18n.t("Не удалось загрузить файл"));return j}
  async function loadImage(sku,seq){let url;try{const r=await fetch('/api/shop/media/'+encodeURIComponent(sku),{headers:{Authorization:'tma '+auth}});if(!r.ok)return;url=URL.createObjectURL(await r.blob());if(seq!==sequence||!$('#sheet').open){URL.revokeObjectURL(url);return}const holder=$('[data-shop-image]');if(holder){const img=document.createElement('img');img.src=url;img.alt=NoraI18n.t("Изображение товара");holder.replaceChildren(img);img.onload=()=>URL.revokeObjectURL(url)}}catch{if(url)URL.revokeObjectURL(url)}}
  async function topup(amount){
    if(busy)return;
    busy=true;
    try{
      const q=await api('shop/topup/prepare',{amount});
      sheet(`
        <span class="eyebrow">${NoraI18n.html("Пополнить кошелёк")}</span>
        <h2>${number(q.amount)} ${plural(q.amount,NoraI18n.t("печенька"),NoraI18n.t("печеньки"),NoraI18n.t("печенек"))}</h2>
        <div class="amount">${number(q.rubles)} ₽</div>
        <p class="sub">${NoraI18n.html("Укажи точную сумму и выбери свой банк. После перевода прикрепи квитанцию для проверки.")}</p>
        <button class="primary" id="sbp-link" type="button">${NoraI18n.html("Оплатить через СБП")} ${arrow()}</button>
        <details class="shop-sbp-qr">
          <summary>${NoraI18n.html("Показать QR-код")}</summary>
          <img src="/shop/ozon-sbp.jpg" alt="${NoraI18n.html("QR-код Ozon Банка для перевода по СБП")}" width="600" height="600" loading="lazy">
        </details>
        <form id="receipt-form">
          <label>${NoraI18n.html("Квитанция")}<input id="shop-receipt" type="file" accept="image/jpeg,image/png,image/webp,application/pdf" required></label>
          <p class="sub">${NoraI18n.html("Фото или PDF, до 5 МБ.")}</p>
          <button class="secondary" type="submit" id="receipt-send">${NoraI18n.html("Отправить на проверку")}</button>
        </form>
      `);
      $('#sbp-link').onclick=()=>tg?.openLink?tg.openLink(q.payment_url):window.open(q.payment_url,'_blank','noopener');
      $('#receipt-form').onsubmit=async e=>{
        e.preventDefault();
        if(busy)return;
        const file=$('#shop-receipt').files?.[0];
        if(!file)return;
        if(file.size>5*1024*1024){toast(NoraI18n.t("Квитанция должна быть не больше 5 МБ"));return}
        busy=true;
        $('#receipt-send').disabled=true;
        try{
          const j=await upload('shop/topup/receipt',q.token,file);
          $('#sheet').close();
          toast(j.message);
          await refresh();
        }catch(err){
          toast(err.message);
          if($('#receipt-send'))$('#receipt-send').disabled=false;
        }finally{busy=false}
      };
    }catch(err){toast(err.message)}finally{busy=false}
  }
  document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.shopCategory!==undefined)navigate(b.dataset.shopCategory);if(b.hasAttribute('data-shop-root'))navigate(null);if(b.dataset.topup)topup(Number(b.dataset.topup));if(b.dataset.tab)queueMicrotask(syncBack)});
  function applyHistoryRoute(){
    backPending=false;
    if(!data)return;
    const next=route();
    tab=['home','commands','shop','pet','lk','wallet','history','notices','admin','interactive','games','friends','community','events','mafia','rocket','sea','durak','barricade','dot','poker'].includes(next.view)?next.view:'home';
    category=tab==='shop'?next.category:null;
    if($('#sheet').open)$('#sheet').close();
    render();
  }
  window.addEventListener('popstate',()=>{
    if(afterGameBack){
      const onExit=afterGameBack;
      afterGameBack=null;
      onExit();
      return;
    }
    const game=currentGame();
    if(game){
      // Restore the guard entry immediately so cancelling Back keeps the game and URL.
      if(!history.state?.noraGameExit)pushGameGuard(game);
      exitGameView(game==='world'?window.NoraGame.close:applyHistoryRoute);
      return;
    }
    applyHistoryRoute();
  });
  function goBack(){
    if(!data||backPending||afterGameBack||$('#game-exit').open)return;
    if(profileOpen()&&$('.avatar-viewer[open]')){$('.avatar-viewer[open]').close();return}
    if(window.NoraProfileTrack?.back?.())return;
    if($('#sheet').open){$('#sheet').close();return}
    if(window.NoraGame?.isOpen?.()){exitGameView(window.NoraGame.close);return}
    if(tab==='durak'&&window.NoraDurak?.back())return;
    if(tab==='barricade'&&barricadeView?.back())return;
    if(tab==='pet'&&history.state?.petFrom){
      backPending=true;
      history.back();
      return;
    }
    const next=parent();
    if(next)goToTab(next);
    else if(tab==='shop')navigate(null);
  }
  tg?.BackButton?.onClick?.(goBack);
  // Profile is a dialog over the current route, not a separate history entry.
  // Watch both opening/closing and content replacement inside the shared sheet.
  const profileBackObserver=new MutationObserver(()=>{
    if(data&&(profileOpen()||profileDialog.classList.contains('native-profile-back')))syncBack();
    else if(!data)profileDialog.classList.remove('native-profile-back');
  });
  profileBackObserver.observe(profileDialog,{attributes:true,attributeFilter:['open']});
  profileBackObserver.observe($('#sheet-content'),{childList:true});
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&!event.defaultPrevented&&!event.repeat&&gameViews.has(tab)&&
        !window.NoraGame?.isOpen?.()&&!document.querySelector('dialog[open]')){
      event.preventDefault();
      goBack();
    }
  });
  return {screen,cards,product,resume,syncBack,svg,route,tabChanged,preloadSeasonal,openCategory:navigate,leaveGameTo,exitGameView};
})();
