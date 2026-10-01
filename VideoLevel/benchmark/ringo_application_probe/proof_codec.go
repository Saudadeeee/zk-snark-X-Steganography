package openingprobe

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"reflect"

	"github.com/sp301415/ringo-snark/buckler"
	"github.com/sp301415/ringo-snark/examples/mult/zp"
)

const (
	openingProofProtocol = "zkstego-ringo-opening-probe-v2"
	maxOpeningProofBytes = 16 << 20
	maxProofSliceEntries = 1 << 20
	openingBinaryMagic   = "RZK2"
)

type openingProofEnvelope struct {
	Protocol string                   `json:"protocol"`
	Proof    *buckler.Proof[*zp.Uint] `json:"proof"`
}

// encodeOpeningProof creates a deterministic JSON wire representation for the
// pinned probe. The exact bytes are research evidence only; this is not a
// versioned production proof format.
func encodeOpeningProof(proof *buckler.Proof[*zp.Uint]) ([]byte, error) {
	if err := validateOpeningProofShape(proof); err != nil {
		return nil, err
	}
	encoded, err := json.Marshal(openingProofEnvelope{
		Protocol: openingProofProtocol,
		Proof:    proof,
	})
	if err != nil {
		return nil, fmt.Errorf("marshal opening proof: %w", err)
	}
	if len(encoded) == 0 || len(encoded) > maxOpeningProofBytes {
		return nil, fmt.Errorf("serialized opening proof size must be between 1 and %d bytes", maxOpeningProofBytes)
	}
	return encoded, nil
}

// decodeOpeningProof accepts only the exact encoding produced by
// encodeOpeningProof. Canonical re-encoding also rejects duplicate JSON keys,
// alternate whitespace, trailing values and unknown fields.
func decodeOpeningProof(encoded []byte) (*buckler.Proof[*zp.Uint], error) {
	if len(encoded) == 0 || len(encoded) > maxOpeningProofBytes {
		return nil, fmt.Errorf("serialized opening proof size must be between 1 and %d bytes", maxOpeningProofBytes)
	}
	decoder := json.NewDecoder(bytes.NewReader(encoded))
	decoder.DisallowUnknownFields()
	var envelope openingProofEnvelope
	if err := decoder.Decode(&envelope); err != nil {
		return nil, fmt.Errorf("decode opening proof: %w", err)
	}
	if envelope.Protocol != openingProofProtocol || envelope.Proof == nil {
		return nil, errors.New("serialized opening proof has an unsupported protocol or empty proof")
	}
	if err := validateOpeningProofShape(envelope.Proof); err != nil {
		return nil, fmt.Errorf("serialized opening proof has invalid structure: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		return nil, errors.New("serialized opening proof has trailing JSON data")
	}
	canonical, err := encodeOpeningProof(envelope.Proof)
	if err != nil {
		return nil, err
	}
	if !bytes.Equal(canonical, encoded) {
		return nil, errors.New("serialized opening proof is not canonical")
	}
	return envelope.Proof, nil
}

// encodeBinaryOpeningProof serializes the pinned proof struct without JSON
// field names or decimal integer expansion. The schema is fixed by this Go
// module revision; this is still a research codec, not a stable wire standard.
func encodeBinaryOpeningProof(proof *buckler.Proof[*zp.Uint]) ([]byte, error) {
	if err := validateOpeningProofShape(proof); err != nil {
		return nil, err
	}
	var output bytes.Buffer
	output.WriteString(openingBinaryMagic)
	if err := encodeProofValue(&output, reflect.ValueOf(proof).Elem()); err != nil {
		return nil, fmt.Errorf("encode binary opening proof: %w", err)
	}
	if output.Len() > maxOpeningProofBytes {
		return nil, fmt.Errorf("binary opening proof exceeds %d bytes", maxOpeningProofBytes)
	}
	return output.Bytes(), nil
}

func decodeBinaryOpeningProof(encoded []byte) (*buckler.Proof[*zp.Uint], error) {
	if len(encoded) <= len(openingBinaryMagic) || len(encoded) > maxOpeningProofBytes {
		return nil, errors.New("binary opening proof size is out of range")
	}
	reader := bytes.NewReader(encoded)
	magic := make([]byte, len(openingBinaryMagic))
	if _, err := io.ReadFull(reader, magic); err != nil || string(magic) != openingBinaryMagic {
		return nil, errors.New("binary opening proof has an invalid header")
	}
	proofValue := reflect.New(reflect.TypeOf(buckler.Proof[*zp.Uint]{}))
	if err := decodeProofValue(reader, proofValue.Elem()); err != nil {
		return nil, fmt.Errorf("decode binary opening proof: %w", err)
	}
	if reader.Len() != 0 {
		return nil, errors.New("binary opening proof has trailing bytes")
	}
	proof := proofValue.Interface().(*buckler.Proof[*zp.Uint])
	if err := validateOpeningProofShape(proof); err != nil {
		return nil, fmt.Errorf("binary opening proof has invalid structure: %w", err)
	}
	canonical, err := encodeBinaryOpeningProof(proof)
	if err != nil {
		return nil, err
	}
	if !bytes.Equal(canonical, encoded) {
		return nil, errors.New("binary opening proof is not canonical")
	}
	return proof, nil
}

func encodeProofValue(output *bytes.Buffer, value reflect.Value) error {
	switch value.Kind() {
	case reflect.Pointer:
		if value.IsNil() {
			return output.WriteByte(0)
		}
		if err := output.WriteByte(1); err != nil {
			return err
		}
		return encodeProofValue(output, value.Elem())
	case reflect.Slice:
		if value.Len() == 0 {
			return errors.New("empty proof slice")
		}
		var length [binary.MaxVarintLen64]byte
		n := binary.PutUvarint(length[:], uint64(value.Len()))
		if _, err := output.Write(length[:n]); err != nil {
			return err
		}
		for i := 0; i < value.Len(); i++ {
			if err := encodeProofValue(output, value.Index(i)); err != nil {
				return fmt.Errorf("slice element %d: %w", i, err)
			}
		}
	case reflect.Array:
		for i := 0; i < value.Len(); i++ {
			if err := encodeProofValue(output, value.Index(i)); err != nil {
				return fmt.Errorf("array element %d: %w", i, err)
			}
		}
	case reflect.Struct:
		for i := 0; i < value.NumField(); i++ {
			if value.Type().Field(i).PkgPath != "" {
				continue
			}
			if err := encodeProofValue(output, value.Field(i)); err != nil {
				return fmt.Errorf("field %s: %w", value.Type().Field(i).Name, err)
			}
		}
	case reflect.Bool:
		if value.Bool() {
			return output.WriteByte(1)
		}
		return output.WriteByte(0)
	case reflect.Uint8:
		return output.WriteByte(byte(value.Uint()))
	case reflect.Uint16:
		var data [2]byte
		binary.LittleEndian.PutUint16(data[:], uint16(value.Uint()))
		_, err := output.Write(data[:])
		return err
	case reflect.Uint32:
		var data [4]byte
		binary.LittleEndian.PutUint32(data[:], uint32(value.Uint()))
		_, err := output.Write(data[:])
		return err
	case reflect.Uint, reflect.Uint64:
		var data [8]byte
		binary.LittleEndian.PutUint64(data[:], value.Uint())
		_, err := output.Write(data[:])
		return err
	case reflect.Int8:
		return output.WriteByte(byte(int8(value.Int())))
	case reflect.Int16:
		var data [2]byte
		binary.LittleEndian.PutUint16(data[:], uint16(value.Int()))
		_, err := output.Write(data[:])
		return err
	case reflect.Int32:
		var data [4]byte
		binary.LittleEndian.PutUint32(data[:], uint32(value.Int()))
		_, err := output.Write(data[:])
		return err
	case reflect.Int:
		var data [8]byte
		binary.LittleEndian.PutUint64(data[:], uint64(value.Int()))
		_, err := output.Write(data[:])
		return err
	case reflect.Int64:
		var data [8]byte
		binary.LittleEndian.PutUint64(data[:], uint64(value.Int()))
		_, err := output.Write(data[:])
		return err
	default:
		return fmt.Errorf("unsupported proof field kind %s", value.Kind())
	}
	return nil
}

func decodeProofValue(reader *bytes.Reader, value reflect.Value) error {
	switch value.Kind() {
	case reflect.Pointer:
		if !value.CanSet() {
			return errors.New("proof pointer destination is not settable")
		}
		present, err := reader.ReadByte()
		if err != nil {
			return err
		}
		if present == 0 {
			value.SetZero()
			return nil
		}
		if present != 1 {
			return errors.New("invalid pointer marker")
		}
		value.Set(reflect.New(value.Type().Elem()))
		return decodeProofValue(reader, value.Elem())
	case reflect.Slice:
		length, err := binary.ReadUvarint(reader)
		if err != nil {
			return err
		}
		if length == 0 || length > maxProofSliceEntries || length > uint64(reader.Len()) {
			return errors.New("proof slice length is out of range")
		}
		result := reflect.MakeSlice(value.Type(), int(length), int(length))
		for i := 0; i < int(length); i++ {
			if err := decodeProofValue(reader, result.Index(i)); err != nil {
				return fmt.Errorf("slice element %d: %w", i, err)
			}
		}
		value.Set(result)
	case reflect.Array:
		for i := 0; i < value.Len(); i++ {
			if err := decodeProofValue(reader, value.Index(i)); err != nil {
				return fmt.Errorf("array element %d: %w", i, err)
			}
		}
	case reflect.Struct:
		for i := 0; i < value.NumField(); i++ {
			if value.Type().Field(i).PkgPath != "" {
				continue
			}
			if err := decodeProofValue(reader, value.Field(i)); err != nil {
				return fmt.Errorf("field %s: %w", value.Type().Field(i).Name, err)
			}
		}
	case reflect.Bool, reflect.Uint8, reflect.Int8:
		b, err := reader.ReadByte()
		if err != nil {
			return err
		}
		if value.Kind() == reflect.Bool {
			if b > 1 {
				return errors.New("invalid boolean encoding")
			}
			value.SetBool(b == 1)
		} else if value.Kind() == reflect.Uint8 {
			value.SetUint(uint64(b))
		} else {
			value.SetInt(int64(int8(b)))
		}
	case reflect.Uint16:
		var data [2]byte
		if _, err := io.ReadFull(reader, data[:]); err != nil {
			return err
		}
		value.SetUint(uint64(binary.LittleEndian.Uint16(data[:])))
	case reflect.Uint32:
		var data [4]byte
		if _, err := io.ReadFull(reader, data[:]); err != nil {
			return err
		}
		value.SetUint(uint64(binary.LittleEndian.Uint32(data[:])))
	case reflect.Uint, reflect.Uint64:
		var data [8]byte
		if _, err := io.ReadFull(reader, data[:]); err != nil {
			return err
		}
		value.SetUint(binary.LittleEndian.Uint64(data[:]))
	case reflect.Int16:
		var data [2]byte
		if _, err := io.ReadFull(reader, data[:]); err != nil {
			return err
		}
		value.SetInt(int64(int16(binary.LittleEndian.Uint16(data[:]))))
	case reflect.Int32:
		var data [4]byte
		if _, err := io.ReadFull(reader, data[:]); err != nil {
			return err
		}
		value.SetInt(int64(int32(binary.LittleEndian.Uint32(data[:]))))
	case reflect.Int:
		var data [8]byte
		if _, err := io.ReadFull(reader, data[:]); err != nil {
			return err
		}
		value.SetInt(int64(binary.LittleEndian.Uint64(data[:])))
	case reflect.Int64:
		var data [8]byte
		if _, err := io.ReadFull(reader, data[:]); err != nil {
			return err
		}
		value.SetInt(int64(binary.LittleEndian.Uint64(data[:])))
	default:
		return fmt.Errorf("unsupported proof field kind %s", value.Kind())
	}
	return nil
}

func validateOpeningProofShape(proof *buckler.Proof[*zp.Uint]) error {
	if proof == nil {
		return errors.New("opening proof is required")
	}
	if missing := missingProofValue(reflect.ValueOf(proof), "proof"); missing != "" {
		return fmt.Errorf("opening proof contains a missing or empty field at %s", missing)
	}
	return nil
}

// missingProofValue finds nil pointers and empty slices at every exported
// level. This does not prove semantic validity; it prevents structurally empty
// JSON objects from reaching the dependency verifier with missing internals.
func missingProofValue(value reflect.Value, path string) string {
	switch value.Kind() {
	case reflect.Interface, reflect.Pointer:
		if value.IsNil() {
			return path
		}
		return missingProofValue(value.Elem(), path)
	case reflect.Slice:
		if value.IsNil() || value.Len() == 0 {
			return path
		}
		for i := 0; i < value.Len(); i++ {
			if missing := missingProofValue(value.Index(i), fmt.Sprintf("%s[%d]", path, i)); missing != "" {
				return missing
			}
		}
	case reflect.Array:
		for i := 0; i < value.Len(); i++ {
			if missing := missingProofValue(value.Index(i), fmt.Sprintf("%s[%d]", path, i)); missing != "" {
				return missing
			}
		}
	case reflect.Struct:
		for i := 0; i < value.NumField(); i++ {
			field := value.Type().Field(i)
			if field.PkgPath != "" ||
				(value.Type() == reflect.TypeOf(buckler.Proof[*zp.Uint]{}) && field.Name == "SumCheckMaskSum") {
				continue
			}
			fieldPath := path + "." + field.Name
			if missing := missingProofValue(value.Field(i), fieldPath); missing != "" {
				return missing
			}
		}
	}
	return ""
}
