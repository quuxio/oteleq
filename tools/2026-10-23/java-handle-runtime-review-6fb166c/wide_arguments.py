"""Independent actual-agent long/double slot controls using frozen maintained oracles."""
import unittest
from unittest.mock import patch
from otelc import witness
import test_java_handle_runtime as handle
import test_witness as direct

class WideArguments(unittest.TestCase):
    def exercise(self, receiver):
        text=handle.source(receiver)
        text=text.replace('int seed)', 'long seed,double ignored)')
        text=text.replace('MethodType.methodType(int.class,int.class)', 'MethodType.methodType(int.class,long.class,double.class)')
        text=text.replace('HANDLE.invokeExact(receiver,seed)', 'HANDLE.invokeExact(receiver,seed,ignored)')
        text=text.replace('HANDLE.invokeExact(seed)', 'HANDLE.invokeExact(seed,ignored)')
        text=text.replace('return wrapper(receiver, seed);', 'return wrapper(receiver, seed,ignored);')
        text=text.replace('return wrapper(seed);', 'return wrapper(seed,ignored);')
        text=text.replace('envelope(receiver, Integer.parseInt(line))', 'envelope(receiver, Long.parseLong(line),Double.parseDouble(line))')
        text=text.replace('envelope(Integer.parseInt(line))', 'envelope(Long.parseLong(line),Double.parseDouble(line))')
        text=text.replace('return seed + offset;', 'return Math.toIntExact(seed + offset);')
        text=text.replace('return seed + 1;', 'return Math.toIntExact(seed + 1);')
        original=witness.compile_bindings
        def compile_wide(application,declarations,output,**options):
            frozen={role:{**row,'descriptor': '()V' if role=='rendezvous' else
                '(LWork;JD)I' if receiver and role in ('wrapper','envelope') else '(JD)I'} for role,row in declarations.items()}
            result=original(application,frozen,output,**options)
            self.assertEqual(result['route']['invoke_descriptor'],'(LWork;JD)I' if receiver else '(JD)I')
            self.assertEqual(result['route']['reference_kind'],5 if receiver else 6)
            return result
        with patch.object(witness,'compile_bindings',side_effect=compile_wide):
            direct.WitnessIntegrationTests.exercise(self,text,receiver=receiver,profile=witness.HANDLE_PROFILE,live_metrics=receiver)
    def test_static_long_double_slots(self):self.exercise(False)
    def test_instance_long_double_slots(self):self.exercise(True)

if __name__=='__main__':unittest.main(verbosity=2)
