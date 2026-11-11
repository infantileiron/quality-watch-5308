export async function readText(file:File){if(file.size>1000000)throw new Error('CSV不可超过1MB');return file.text()}
