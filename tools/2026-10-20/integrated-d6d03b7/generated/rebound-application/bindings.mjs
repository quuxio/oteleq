#!/usr/bin/env node
'use strict';
// Unicode prologue: 😀
let counter=0;
function selected(value){counter+=value+1;return counter;}
selected(0);
selected=(value)=>counter;
