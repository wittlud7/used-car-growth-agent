async (page) => {
  const errors=[];
  await page.locator('[data-view=work]').click();
  page.on('pageerror',e=>errors.push(e.message));
  const stamp=String(Date.now());
  const unsafeName='<img src=x onerror=alert(1)>';
  const csv='name,channel,text\n"'+unsafeName+'",导入验收,"北京，预算12万，这周买SUV。'+stamp+'"\nCSV拒绝-'+stamp+',导入验收,"上海，预算18万，本月想买。\n请不要联系。"';
  await page.getByRole('button',{name:'＋ 导入咨询',exact:true}).click();
  await page.locator('#import-file').setInputFiles({name:'synthetic.csv',mimeType:'text/csv',buffer:Buffer.from(csv,'utf8')});
  await page.locator('#import-dialog').waitFor({state:'hidden'});
  await page.getByRole('button',{name:'运行规则分析 →',exact:true}).click();
  await page.getByLabel('跟进负责人').waitFor();
  if(await page.locator('#detail img').count())throw Error('Unescaped HTML in customer name');
  await page.getByLabel('运行方式').selectOption('llm');
  await page.getByRole('button',{name:'用模型重跑 ↻',exact:true}).click();
  await page.locator('#global-status').getByText('模型API尚未配置；先用规则演示，配置方法见 README。',{exact:true}).waitFor();
  await page.getByLabel('运行方式').selectOption('rules');
  await page.getByRole('button',{name:'查看CSV拒绝-'+stamp+'的咨询',exact:true}).click();
  await page.getByRole('button',{name:'运行规则分析 →',exact:true}).click();
  await page.locator('#detail').getByText('D · 停止联系',{exact:true}).waitFor();
  if(await page.getByRole('button',{name:'通过审核 →',exact:true}).count())throw Error('Opt-out can be approved in UI');
  await page.getByRole('button',{name:'驳回归档',exact:true}).click();
  await page.getByLabel('实际结果 / 原因').fill('合成验收：拒绝联系，驳回归档。');
  await page.getByRole('button',{name:'确认登记',exact:true}).click();
  await page.locator('#outcome-dialog').waitFor({state:'hidden'});
  if(errors.length)throw Error(errors.join('; '));
  return {ok:true,pageErrors:errors,checks:['UTF8-CSV','quoted-newline','escaped-HTML','unconfigured-model-message','no-silent-fallback','opt-out-no-approval','rejection-record']};
}
