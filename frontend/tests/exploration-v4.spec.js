import { test, expect } from '@playwright/test'

async function privateProfile(page) {
  const username=`growth_${Date.now()}`
  expect((await page.request.post('/api/auth/register',{data:{username,nickname:'成长路线测试',password:'GrowthTesting123!'}})).status()).toBe(201)
  await page.goto('/login')
  await page.getByLabel('用户名',{exact:true}).fill(username)
  await page.getByLabel('密码',{exact:true}).fill('GrowthTesting123!')
  await page.getByRole('button',{name:'登录',exact:true}).click()
  await expect(page.getByRole('button',{name:'退出',exact:true})).toBeVisible()
  await page.getByLabel('演示数据',{exact:true}).check()
  await page.goto('/profile')
  await expect(page.getByRole('button',{name:'保存新版本 →',exact:true})).toBeEnabled()
  await page.getByLabel('已掌握技能',{exact:true}).fill('Python、SQL')
  await page.getByLabel('偏好城市',{exact:true}).fill('长沙、衡阳')
  await page.getByRole('button',{name:'保存新版本 →',exact:true}).click()
  await expect(page.getByRole('status')).toContainText('已保存')
}

// Exercise the browser history route event, without reloading the component.
async function historyRoute(page, url) {
  await page.evaluate(url=>{
    const state={...window.history.state,current:url}
    window.history.replaceState(state,'',url)
    window.dispatchEvent(new PopStateEvent('popstate',{state}))
  },url)
}

test('linked charts share exact scope, expose quality and drill into matching opportunities',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  await page.goto('/analytics?data_kind=demo')
  await expect(page.getByRole('table',{name:'公告字段完整性'}).locator('tbody tr')).toHaveCount(6)
  await page.getByRole('button',{name:'按发展路径筛选企业就业',exact:true}).click()
  await expect(page).toHaveURL(/path=employment/)
  await page.getByRole('button',{name:'按城市筛选长沙',exact:true}).click()
  await expect(page.getByRole('group',{name:'按城市联动'}).getByRole('button')).toHaveCount(1)
  await page.getByRole('group',{name:'按发布月份联动'}).getByRole('button').first().click()
  await expect(page).toHaveURL(/start_date=/)
  await expect(page.getByRole('button',{name:'复制当前分析链接',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'复制当前分析链接',exact:true}).click()
  const shared=page.getByRole('textbox',{name:'当前分析链接',exact:true})
  await expect(shared).toBeVisible()
  const scope=new URL(await shared.inputValue()).searchParams
  expect(scope.get('city')).toBe('长沙')
  expect(scope.get('path')).toBe('employment')
  expect(scope.get('data_kind')).toBe('demo')
  const urlBefore=page.url()
  await page.screenshot({path:'../.local/linked-analytics-desktop.png',fullPage:true})
  await page.setViewportSize({width:390,height:844})
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:'../.local/linked-analytics-mobile.png',fullPage:true})
  await page.getByRole('group',{name:'从技能查看机会'}).getByRole('button').first().click()
  await expect(page).toHaveURL(/\/opportunities\?/)
  await expect(page.locator('.opportunity-card').first()).toBeVisible()
  const query=new URL(page.url()).searchParams
  expect(query.get('start_date')).toBe(scope.get('start_date'))
  expect(query.get('city')).toBe('长沙')
  expect(query.get('include_expired')).toBe('true')
  const list=(await (await page.request.get('/api/opportunities?'+query)).json())
  expect(list.length).toBeGreaterThan(0)
  expect(list.every(item=>item.city==='长沙' && item.path==='employment' && item.skills.includes(query.get('skill')))).toBe(true)
  await expect(page.locator('.opportunity-card')).toHaveCount(list.length)
  await page.goto(urlBefore)
  await expect(page.getByRole('group',{name:'按城市联动'}).getByRole('button')).toHaveCount(1)
  expect(errors).toEqual([])
})

test('student picks three evidence-based skills, exports a plan and clears demo when public is selected',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  await privateProfile(page)
  await page.goto('/skills')
  const choices=page.locator('.roadmap-skill-choice input')
  await expect(choices.first()).toBeChecked()
  expect(await choices.count()).toBeGreaterThan(3)
  await choices.nth(1).check();await choices.nth(2).check()
  await expect(choices.nth(3)).toBeDisabled()
  await page.locator('.roadmap-evidence summary').first().click()
  await expect(page.locator('.roadmap-evidence li').first()).toContainText('截止')
  const event=page.waitForEvent('download')
  await page.getByRole('button',{name:'导出 Markdown 计划 ↓',exact:true}).click()
  const download=await event
  expect(download.suggestedFilename()).toMatch(/^my-skill-plan-demo-.*\.md$/)
  const stream=await download.createReadStream(),parts=[]
  for await (const part of stream) parts.push(part)
  const plan=Buffer.concat(parts).toString('utf8')
  expect(plan).toContain('第14天复盘')
  expect(plan).toContain('来源证据')
  expect(plan).toContain('模拟演示')
  await page.screenshot({path:'../.local/skill-roadmap-desktop.png',fullPage:true})
  await page.setViewportSize({width:390,height:844})
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:'../.local/skill-roadmap-mobile.png',fullPage:true})
  await page.getByLabel('演示数据',{exact:true}).uncheck()
  await expect(page.getByRole('heading',{name:'当前范围还没有可用的机会线索',exact:true})).toBeVisible()
  await expect(page.locator('.roadmap-skill-card')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('history navigation applies filters even when a matching input was edited but not submitted',async({page})=>{
  await page.goto('/analytics?data_kind=demo')
  await expect(page.getByRole('group',{name:'按城市联动'}).getByRole('button')).not.toHaveCount(1)
  await page.getByRole('textbox',{name:'机会城市',exact:true}).fill('长沙')
  await historyRoute(page,'/analytics?data_kind=demo&city=长沙')
  await expect(page.getByRole('group',{name:'按城市联动'}).getByRole('button')).toHaveCount(1)
  await expect(page.getByRole('button',{name:'按城市筛选长沙',exact:true})).toBeVisible()
  await page.goto('/opportunities?data_kind=demo&include_expired=true')
  await expect(page.locator('.opportunity-card').first()).toBeVisible()
  await page.getByRole('textbox',{name:'城市',exact:true}).fill('长沙')
  const event=page.waitForResponse(r=>r.url().includes('/api/opportunities?')&&new URL(r.url()).searchParams.get('city')==='长沙')
  await historyRoute(page,'/opportunities?data_kind=demo&city=长沙&include_expired=true')
  const response=await event
  const records=await response.json()
  expect(records.length).toBeGreaterThan(0)
  await expect(page.locator('.opportunity-card')).toHaveCount(records.length)
  expect(records.every(item=>item.city==='长沙')).toBe(true)
})

test('URL mode switch releases a pending recommendation and cannot leave demo cards after public failure',async({page})=>{
  await privateProfile(page)
  await page.goto('/opportunities?data_kind=demo')
  await expect(page.locator('.opportunity-card').first()).toBeVisible()
  let release,started
  const gate=new Promise(resolve=>{release=resolve}),begin=new Promise(resolve=>{started=resolve})
  await page.route('**/api/recommendations?data_kind=demo',async route=>{
    const response=await route.fetch();started();await gate;await route.fulfill({response})
  })
  await page.route(/\/api\/opportunities\?.*data_kind=public/,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'公开来源暂不可用（浏览器测试）'})}))
  const completed=page.waitForResponse(r=>r.url().includes('/api/recommendations?data_kind=demo'))
  await page.getByRole('button',{name:'生成我的推荐 ↗',exact:true}).click()
  await begin
  await historyRoute(page,'/opportunities?data_kind=public')
  await expect(page.getByRole('alert')).toContainText('公开来源暂不可用')
  await expect(page.getByRole('button',{name:'生成我的推荐 ↗',exact:true})).toBeEnabled()
  await expect(page.locator('.opportunity-card')).toHaveCount(0)
  release();await (await completed).finished()
  await expect(page.locator('.recommendation-card')).toHaveCount(0)
  await expect(page.getByLabel('演示数据',{exact:true})).not.toBeChecked()
})
