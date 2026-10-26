// Run through playwright-cli run-code against a separate local QA database.
async (page) => {
  const errors=[];
  await page.locator('[data-view=work]').click();
  const testName='验收客户-'+Date.now();
  page.on('pageerror', e=>errors.push(e.message));
  await page.getByRole('button',{name:'＋ 导入咨询',exact:true}).click();
  await page.locator('#import-dialog').getByLabel('客户称呼').fill(testName);
  await page.getByLabel('咨询来源').selectOption('自然咨询');
  await page.getByLabel('咨询原文').fill('我在北京，预算12到15万，想看卡罗拉，这周能看车吗？（合成验收数据）');
  await page.getByRole('button',{name:'加入收件箱 →',exact:true}).click();
  await page.getByRole('button',{name:'运行规则分析 →',exact:true}).click();
  await page.getByLabel('跟进负责人').waitFor();
  await page.getByRole('button',{name:'驳回归档',exact:true}).click();
  await page.locator('#outcome-dialog').getByRole('button',{name:'关闭',exact:true}).click();
  // Missing owner must not advance a draft.
  await page.getByRole('button',{name:'通过审核 →',exact:true}).click();
  await page.locator('#global-status').getByText('通过审核前请填写负责人',{exact:true}).waitFor();
  await page.getByLabel('跟进负责人').fill('模拟顾问（流程验收）');
  await page.getByLabel('跟进草稿').fill('模拟演示话术：请确认方便的看车时间，所有车辆信息由人工核实。');
  await page.getByRole('button',{name:'通过审核 →',exact:true}).click();
  await page.getByRole('button',{name:'登记已联系',exact:true}).waitFor();
  for (const label of ['登记已联系','登记预约','登记成交']) {
    await page.getByRole('button',{name:label,exact:true}).click();
    await page.getByLabel('实际结果 / 原因').fill('合成流程验收，模拟结果，无真实客户、消息或交易。');
    await page.getByRole('button',{name:'确认登记',exact:true}).click();
    await page.locator('#outcome-dialog').waitFor({state:'hidden'});
  }
  await page.reload();
  await page.getByRole('button',{name:'查看'+testName+'的咨询',exact:true}).click();
  await page.locator('#detail .lock-note').getByText('已成交',{exact:false}).waitFor();
  if(await page.getByLabel('跟进草稿').inputValue()!=='模拟演示话术：请确认方便的看车时间，所有车辆信息由人工核实。') throw Error('Edited draft did not persist');
  await page.getByRole('button',{name:'▥ 复盘与评估',exact:true}).click();
  await page.getByRole('button',{name:'运行规则评估 ↗',exact:true}).click();
  await page.locator('#evaluation tbody tr').first().waitFor();
  const cases=await page.locator('#evaluation tbody tr').count();
  if(cases!==12)throw Error('Expected 12 evaluation rows');
  const result=await page.evaluate(()=>({caseRows:document.querySelectorAll('#evaluation tbody tr').length, channelRows:document.querySelectorAll('#channels tr').length, funnel:document.querySelector('#funnel').innerText, horizontalOverflow:document.documentElement.scrollWidth>innerWidth}));
  if(errors.length)throw Error(errors.join('; '));
  return {ok:true,...result,pageErrors:errors,steps:['import','rules','owner-validation','edit-draft','approve','contact','appointment','won','reload-persistence','channel-review','evaluation']};
}
