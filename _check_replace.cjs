const fs = require('fs');
const src = fs.readFileSync('desktop-dashboard/index.html', 'utf8');
const tag = '<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>';
console.log('has tag', src.includes(tag), 'has window.THREE', src.includes('window.THREE'));
const out = src.replace(tag, '<script>/*inline*/</script>');
console.log('replaced', out.length !== src.length);
