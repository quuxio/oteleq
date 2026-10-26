class Counter{static total=0;static delta=0;constructor(start){this.value=start;this.self=this;}
collectionOff(value){this.value+=value;Counter.total+=value;process.stdout.write(Buffer.from([0,255,10]));process.stderr.write(Buffer.from([1,255,10]));return 42;}
emissionOff(value){this.value+=value;Counter.total+=value;process.stdout.write(Buffer.from([0,255,10]));process.stderr.write(Buffer.from([1,255,10]));return 42;}
bothOff(value){this.value+=value;Counter.total+=value;process.stdout.write(Buffer.from([0,255,10]));process.stderr.write(Buffer.from([1,255,10]));return 42;}
}
